"""Connection helpers for MySQL (source) and PostgreSQL (target)."""
from __future__ import annotations

import logging

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config

log = logging.getLogger("db")


def mysql_engine() -> Engine:
    return create_engine(config.mysql_url(), pool_pre_ping=True)


def pg_engine() -> Engine:
    return create_engine(config.pg_url(), pool_pre_ping=True)


def pg_connect():
    """Raw psycopg2 connection (used for execute_values batch inserts)."""
    c = config.PG
    return psycopg2.connect(host=c["host"], port=c["port"], user=c["user"],
                            password=c["password"], dbname=c["database"])


def ensure_mysql_database() -> None:
    eng = create_engine(config.mysql_url(with_db=False))
    with eng.begin() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL['database']}` "
                          "CHARACTER SET utf8mb4"))
    eng.dispose()


def ensure_postgres_database() -> None:
    """Create the target database if it doesn't exist (connects via 'postgres' db)."""
    eng = create_engine(config.pg_url("postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"),
                              {"n": config.PG["database"]}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{config.PG["database"]}"'))
            log.info("created PostgreSQL database %s", config.PG["database"])
    eng.dispose()


def run_sql_script(engine: Engine, path, split_statements: bool = False) -> None:
    """Execute a .sql file. MySQL needs statement splitting; psycopg2 does not."""
    sql = path.read_text()
    with engine.begin() as conn:
        if split_statements:
            for stmt in (s.strip() for s in sql.split(";")):
                # drop leading comment-only chunks
                body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
                if body:
                    conn.execute(text(body))
        else:
            conn.exec_driver_sql(sql)
