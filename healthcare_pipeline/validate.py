"""VALIDATE: run the SQL reconciliation / integrity / error-detection suites.

SQL files in sql/validation/ hold named queries:

    -- name: some_check
    -- description: what it proves
    -- expect: zero_rows | info
    SELECT ...;

* ``zero_rows``  query returns *violations*; any row => FAIL
* ``info``       query is shown in the report, never fails

Cross-database checks (MySQL source vs PostgreSQL target) cannot be done in one SQL
statement, so they live here in Python.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config
from .db import mysql_engine, pg_engine

log = logging.getLogger("validate")
SUITES = [  # (file, engine key)
    ("01_reconciliation.sql", "pg"), ("02_referential_integrity.sql", "pg"),
    ("03_data_integrity.sql", "pg"), ("04_migration_errors.sql", "pg"),
    ("05_source_mysql_profile.sql", "mysql"),
]


@dataclass
class CheckResult:
    suite: str
    name: str
    description: str
    status: str                       # PASS | FAIL | INFO | ERROR
    rows: int = 0
    data: pd.DataFrame | None = field(default=None, repr=False)
    detail: str = ""


def parse_sql_file(path: Path) -> list[dict]:
    text_ = path.read_text()
    blocks = re.split(r"(?m)^-- name:\s*", text_)[1:]
    queries = []
    for b in blocks:
        lines = b.splitlines()
        name = lines[0].strip()
        meta, sql_lines = {}, []
        for ln in lines[1:]:
            m = re.match(r"--\s*(description|expect):\s*(.*)", ln)
            if m:
                meta[m.group(1)] = m.group(2).strip()
            elif not ln.strip().startswith("-- ====") and not ln.strip().startswith("-- 0"):
                sql_lines.append(ln)
        sql = "\n".join(sql_lines).strip().rstrip(";")
        queries.append({"name": name, "description": meta.get("description", ""),
                        "expect": meta.get("expect", "info"), "sql": sql})
    return queries


def run_suite(engine: Engine, filename: str) -> list[CheckResult]:
    out = []
    for q in parse_sql_file(config.SQL_DIR / "validation" / filename):
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(q["sql"]), conn)
            if q["expect"] == "zero_rows":
                status = "PASS" if df.empty else "FAIL"
            else:
                status = "INFO"
            out.append(CheckResult(filename, q["name"], q["description"], status, len(df), df))
        except Exception as exc:                                    # noqa: BLE001
            out.append(CheckResult(filename, q["name"], q["description"], "ERROR", 0, None,
                                   str(exc).splitlines()[0]))
    return out


# --------------------------------------------------------------------------- cross-database checks
def cross_db_checks(my: Engine, pg: Engine) -> list[CheckResult]:
    res: list[CheckResult] = []
    S = "cross_db"

    def scalar(engine, sql):
        with engine.connect() as c:
            return c.execute(text(sql)).scalar()

    # 1. source row counts == audit.source_rows
    with pg.connect() as c:
        audit = pd.read_sql(text("SELECT table_name, source_rows FROM healthcare.migration_audit"), c)
    bad = []
    for r in audit.itertuples():
        n = scalar(my, f"SELECT COUNT(*) FROM {r.table_name}")
        if n != r.source_rows:
            bad.append({"table": r.table_name, "mysql_count": n, "audit_source_rows": r.source_rows})
    res.append(CheckResult(S, "mysql_source_count_equals_audit_source_rows",
                           "rows extracted must equal rows currently in the MySQL source",
                           "FAIL" if bad else "PASS", len(bad), pd.DataFrame(bad)))

    # 2. money conservation
    src_total = scalar(my, "SELECT COALESCE(SUM(total_amount),0) FROM billing")
    with pg.connect() as c:
        tgt_total = c.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM healthcare.billing")).scalar()
        q_total = c.execute(text(
            "SELECT COALESCE(SUM(CAST(raw_record ->> 'total_amount' AS NUMERIC)),0) "
            "FROM healthcare.migration_errors WHERE table_name = 'billing'")).scalar()
    diff = src_total - (tgt_total + q_total)
    res.append(CheckResult(
        S, "billing_money_is_conserved",
        "MySQL SUM(total_amount) = PostgreSQL SUM(total_amount) + amount held in quarantine (rejected/merged/failed)",
        "PASS" if diff == 0 else "FAIL", 0 if diff == 0 else 1,
        pd.DataFrame([{"mysql_total": src_total, "pg_loaded": tgt_total, "pg_quarantined": q_total, "difference": diff}]),
        f"source={src_total} loaded={tgt_total} quarantined={q_total}"))

    # 3. MRN set comparison (nothing invented, nothing silently lost)
    with my.connect() as c:
        src = set(pd.read_sql(text("SELECT DISTINCT UPPER(TRIM(mrn)) AS mrn FROM patients WHERE mrn IS NOT NULL"), c)["mrn"])
    with pg.connect() as c:
        tgt = set(pd.read_sql(text("SELECT mrn FROM healthcare.patients"), c)["mrn"])
        rej = set(pd.read_sql(text(
            "SELECT DISTINCT upper(btrim(raw_record ->> 'mrn')) AS mrn FROM healthcare.migration_errors "
            "WHERE table_name = 'patients' AND error_category <> 'MERGED_DUPLICATE' AND raw_record ->> 'mrn' IS NOT NULL"), c)["mrn"])
    invented = sorted(tgt - src)
    lost = sorted(src - tgt - rej)
    res.append(CheckResult(S, "no_mrn_invented_in_target", "every target MRN must exist in the source",
                           "FAIL" if invented else "PASS", len(invented), pd.DataFrame({"mrn": invented})))
    res.append(CheckResult(S, "no_mrn_silently_lost", "every source MRN is either in the target or quarantined",
                           "FAIL" if lost else "PASS", len(lost), pd.DataFrame({"mrn": lost})))

    # 4. distinct MRNs in source (valid ones) bound the target size
    res.append(CheckResult(S, "target_patients_not_more_than_distinct_source_mrns",
                           "after de-duplication patients <= distinct source MRNs",
                           "PASS" if len(tgt) <= len(src) else "FAIL", 0, None, f"target={len(tgt)} distinct_source_mrn={len(src)}"))
    return res


# --------------------------------------------------------------------------- report
def _markdown(results: list[CheckResult]) -> str:
    n = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "ERROR", "INFO")}
    L = [f"# Validation report", f"_Generated {datetime.now():%Y-%m-%d %H:%M:%S}_", "",
         f"**{n['PASS']} passed · {n['FAIL']} failed · {n['ERROR']} errored · {n['INFO']} informational**", "",
         "| Suite | Check | Status | Rows |", "|---|---|---|---:|"]
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "ERROR": "⚠️ ERROR", "INFO": "ℹ️ INFO"}
    for r in results:
        L.append(f"| {r.suite} | `{r.name}` | {icon[r.status]} | {r.rows} |")
    L.append("")
    for r in results:
        if r.status in ("INFO", "FAIL", "ERROR"):
            L += [f"### {r.name} — {r.status}", f"_{r.description}_", ""]
            if r.status == "ERROR":
                L.append(f"```\n{r.detail}\n```")
            elif r.data is not None and not r.data.empty:
                L.append(r.data.head(25).to_markdown(index=False))
            else:
                L.append("_no rows returned_")
            L.append("")
    return "\n".join(L)


def run_validation(include_source_profile: bool = True, write_report: bool = True,
                   quiet: bool = False) -> tuple[list[CheckResult], bool]:
    my, pg = mysql_engine(), pg_engine()
    results: list[CheckResult] = []
    for fname, which in SUITES:
        if which == "mysql" and not include_source_profile:
            continue
        results += run_suite(pg if which == "pg" else my, fname)
    results += cross_db_checks(my, pg)

    if write_report:
        (config.REPORT_DIR / "validation_report.md").write_text(_markdown(results))
        (config.REPORT_DIR / "validation_report.json").write_text(json.dumps(
            [dict(suite=r.suite, check=r.name, status=r.status, rows=r.rows, description=r.description,
                  detail=r.detail) for r in results], indent=2))
    ok = not any(r.status in ("FAIL", "ERROR") for r in results)
    if quiet:
        return results, ok
    for r in results:
        if r.status != "INFO":
            log.info("%-7s %-14s %s%s", r.status, r.suite.split("_")[0], r.name,
                     f"  ({r.rows} violating rows)" if r.status == "FAIL" else f"  [{r.detail}]" if r.status == "ERROR" else "")
    log.info("validation: %d pass, %d fail, %d error -> %s",
             sum(r.status == "PASS" for r in results), sum(r.status == "FAIL" for r in results),
             sum(r.status == "ERROR" for r in results), "OK" if ok else "PROBLEMS FOUND")
    return results, ok
