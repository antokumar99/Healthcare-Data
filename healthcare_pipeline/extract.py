"""EXTRACT: stream tables out of MySQL in chunks and keep a raw staging copy."""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config

log = logging.getLogger("extract")


def extract_table(engine: Engine, table: str, chunksize: int = 5000, save: bool = True) -> pd.DataFrame:
    """Read a table with a server-side stream, chunk by chunk, so memory stays bounded."""
    frames = []
    with engine.connect().execution_options(stream_results=True) as conn:
        for chunk in pd.read_sql(text(f"SELECT * FROM {table} ORDER BY 1"), conn, chunksize=chunksize):
            frames.append(chunk)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    log.info("extracted %-13s %6d rows", table, len(df))
    if save:
        df.to_csv(config.STAGING_DIR / f"raw_{table}.csv", index=False)
    return df


def extract_all(engine: Engine) -> dict[str, pd.DataFrame]:
    return {t: extract_table(engine, t) for t in ("patients", "appointments", "billing")}
