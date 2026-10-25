"""Load the generated CSVs into the legacy MySQL database (the migration *source*)."""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text

from . import config
from .db import ensure_mysql_database, mysql_engine, run_sql_script

log = logging.getLogger("load_source")
TABLES = ["patients", "appointments", "billing"]
DATE_COLS = {"patients": ["created_at"], "appointments": ["appointment_datetime", "created_at"],
             "billing": ["billing_date"]}


def load_source(raw_dir=config.RAW_DIR, chunk: int = 2000) -> dict[str, int]:
    ensure_mysql_database()
    eng = mysql_engine()
    run_sql_script(eng, config.SQL_DIR / "mysql_schema.sql", split_statements=True)
    counts = {}
    for t in TABLES:
        # read everything as string first so empty cells stay NULL and nothing gets re-typed
        df = pd.read_csv(raw_dir / f"{t}.csv", dtype=str, keep_default_na=False, na_values=[""])
        for col in ("duration_minutes",):
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        df = df.astype(object).where(df.notna(), None)
        df.to_sql(t, eng, if_exists="append", index=False, chunksize=chunk, method="multi")
        with eng.connect() as c:
            counts[t] = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        log.info("MySQL source: loaded %-13s %6d rows", t, counts[t])
    return counts
