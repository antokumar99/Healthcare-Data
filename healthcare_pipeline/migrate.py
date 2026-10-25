"""LOAD: MySQL -> PostgreSQL migration.

extract (MySQL) -> clean (pandas) -> create target schema -> batch insert (psycopg2
execute_values) -> quarantine rejects/duplicates -> reset identity sequences ->
write control totals to healthcare.migration_audit.

Batch-insert strategy
---------------------
Rows are inserted in batches inside a SAVEPOINT.  If a batch fails (a constraint the
cleaner didn't anticipate), we roll back to the savepoint and retry that batch row by
row, so one bad row never takes down 999 good ones.  Each failing row is written to
healthcare.migration_errors as category LOAD_FAILURE with its full payload.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd

try:
    from psycopg2.extras import execute_values  # pyright: ignore[reportMissingModuleSource]
except ModuleNotFoundError:  # pragma: no cover
    execute_values = None

from . import config
from .cleaning import CleanResult, clean_all, cleaning_report_markdown
from .db import ensure_postgres_database, mysql_engine, pg_connect, pg_engine, run_sql_script
from .extract import extract_all
from .schema_mapping import PK, TARGET_COLUMNS, render_mapping_markdown

log = logging.getLogger("migrate")
LOAD_ORDER = ["patients", "appointments", "billing"]          # parents before children
MONEY_COLS = {"total_amount", "insurance_paid", "patient_responsibility"}


# --------------------------------------------------------------------------- value conversion
def _py(v, col: str):
    if v is None or v is pd.NaT or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return None
    if col in MONEY_COLS:
        return Decimal(str(round(float(v), 2)))
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        return v.item()
    return v


def to_records(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    return [tuple(_py(v, c) for v, c in zip(row, columns)) for row in df[columns].itertuples(index=False, name=None)]


def _json_default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


# --------------------------------------------------------------------------- loading
def batch_insert(conn, run_id, table: str, df: pd.DataFrame, batch_size: int) -> tuple[int, int]:
    """Insert df into healthcare.<table>. Returns (loaded_rows, failed_rows)."""
    cols = TARGET_COLUMNS[table]
    records = to_records(df, cols)
    sql = f"INSERT INTO {config.PG_SCHEMA}.{table} ({', '.join(cols)}) VALUES %s"
    loaded = failed = 0
    cur = conn.cursor()
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        cur.execute("SAVEPOINT batch_sp")
        try:
            execute_values(cur, sql, batch, page_size=len(batch))
            cur.execute("RELEASE SAVEPOINT batch_sp")
            loaded += len(batch)
        except Exception as exc:                       # noqa: BLE001 - we want every DB error here
            cur.execute("ROLLBACK TO SAVEPOINT batch_sp")
            log.warning("%s: batch %d-%d failed (%s) - retrying row by row",
                        table, start, start + len(batch), str(exc).splitlines()[0])
            for rec in batch:
                cur.execute("SAVEPOINT row_sp")
                try:
                    cur.execute(f"INSERT INTO {config.PG_SCHEMA}.{table} ({', '.join(cols)}) "
                                f"VALUES ({', '.join(['%s'] * len(cols))})", rec)
                    cur.execute("RELEASE SAVEPOINT row_sp")
                    loaded += 1
                except Exception as row_exc:           # noqa: BLE001
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    failed += 1
                    payload = json.dumps(dict(zip(cols, rec)), default=_json_default)
                    cur.execute(
                        f"INSERT INTO {config.PG_SCHEMA}.migration_errors "
                        "(run_id, table_name, source_id, error_category, error_type, error_message, raw_record) "
                        "VALUES (%s,%s,%s,'LOAD_FAILURE',%s,%s,%s::jsonb)",
                        (run_id, table, rec[0], type(row_exc).__name__, str(row_exc).splitlines()[0], payload))
        conn.commit()
        log.info("%-13s batch %4d-%-4d committed (%d/%d loaded)", table, start, start + len(batch),
                 loaded, len(records))
    return loaded, failed


def quarantine(conn, run_id, table: str, errors: pd.DataFrame, category: str) -> None:
    if errors.empty:
        return
    rows = [(str(run_id), table, int(r.source_id), category, r.error_type, r.error_message, r.raw_record)
            for r in errors.itertuples(index=False)]
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"INSERT INTO {config.PG_SCHEMA}.migration_errors "
            "(run_id, table_name, source_id, error_category, error_type, error_message, raw_record) VALUES %s",
            rows, template="(%s,%s,%s,%s,%s,%s,%s::jsonb)", page_size=1000)
    conn.commit()


def reset_sequences(conn) -> None:
    with conn.cursor() as cur:
        for table, pk in PK.items():
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{config.PG_SCHEMA}.{table}', '{pk}'), "
                        f"COALESCE((SELECT MAX({pk}) FROM {config.PG_SCHEMA}.{table}), 1))")
    conn.commit()


def id_checksum(ids) -> str:
    return hashlib.md5(",".join(str(i) for i in sorted(int(x) for x in ids)).encode()).hexdigest()


def write_audit(conn, run_id, res: CleanResult, loaded: int, failed: int, started, completed) -> None:
    amount = None
    if res.table == "billing":
        amount = sum((Decimal(str(round(float(v), 2))) for v in res.clean["total_amount"]), Decimal("0.00"))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {config.PG_SCHEMA}.migration_audit "
            "(run_id, table_name, source_rows, duplicates_merged, rejected_rows, expected_load_rows, "
            " loaded_rows, load_failures, expected_id_checksum, expected_amount_sum, started_at, completed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (str(run_id), res.table, res.source_rows, len(res.duplicates), len(res.rejects), len(res.clean),
             loaded, failed, id_checksum(res.clean[PK[res.table]]), amount, started, completed))
    conn.commit()


# --------------------------------------------------------------------------- orchestration
def run_migration(batch_size: int = config.BATCH_SIZE) -> dict:
    run_id = uuid.uuid4()
    t0 = time.time()
    log.info("=== migration run %s ===", run_id)

    # 1. EXTRACT
    raw = extract_all(mysql_engine())

    # 2. TRANSFORM
    results = clean_all(raw)
    for t, r in results.items():
        r.clean.to_csv(config.STAGING_DIR / f"clean_{t}.csv", index=False)
        pd.concat([r.rejects.assign(category="REJECTED"), r.duplicates.assign(category="MERGED_DUPLICATE")]) \
            .to_csv(config.REPORT_DIR / f"quarantine_{t}.csv", index=False)
    (config.REPORT_DIR / "cleaning_report.md").write_text(cleaning_report_markdown(results))
    (config.DOCS_DIR / "schema_mapping.md").write_text(render_mapping_markdown())

    # 3. LOAD
    ensure_postgres_database()
    run_sql_script(pg_engine(), config.SQL_DIR / "postgres_schema.sql")
    log.info("target schema '%s' (re)created", config.PG_SCHEMA)
    summary = {}
    conn = pg_connect()
    try:
        for table in LOAD_ORDER:
            res = results[table]
            started = datetime.now()
            loaded, failed = batch_insert(conn, run_id, table, res.clean, batch_size)
            quarantine(conn, run_id, table, res.rejects, "REJECTED")
            quarantine(conn, run_id, table, res.duplicates, "MERGED_DUPLICATE")
            write_audit(conn, run_id, res, loaded, failed, started, datetime.now())
            summary[table] = {**res.summary, "loaded": loaded, "load_failures": failed}
        reset_sequences(conn)
    finally:
        conn.close()

    summary["_meta"] = {"run_id": str(run_id), "seconds": round(time.time() - t0, 2)}
    log.info("migration finished in %.1fs", summary["_meta"]["seconds"])
    return summary
