"""Central configuration: paths, DB connection settings, logging."""
import logging
import os
from pathlib import Path
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
STAGING_DIR = ROOT / "data" / "staging"
REPORT_DIR = ROOT / "reports"
SQL_DIR = ROOT / "sql"
DOCS_DIR = ROOT / "docs"
for _d in (RAW_DIR, STAGING_DIR, REPORT_DIR, DOCS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SEED = int(os.getenv("RANDOM_SEED", "42"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))

MYSQL = dict(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", "rootpass"),
    database=os.getenv("MYSQL_DATABASE", "healthcare_legacy"),
)
PG = dict(
    host=os.getenv("PG_HOST", "localhost"),
    port=int(os.getenv("PG_PORT", "5432")),
    user=os.getenv("PG_USER", "postgres"),
    password=os.getenv("PG_PASSWORD", "postgres"),
    database=os.getenv("PG_DATABASE", "healthcare_target"),
)

PG_SCHEMA = "healthcare"


def mysql_url(with_db: bool = True) -> str:
    c = MYSQL
    db = c["database"] if with_db else ""
    return f"mysql+pymysql://{c['user']}:{quote_plus(c['password'])}@{c['host']}:{c['port']}/{db}"


def pg_url(database: str | None = None) -> str:
    c = PG
    return (f"postgresql+psycopg2://{c['user']}:{quote_plus(c['password'])}"
            f"@{c['host']}:{c['port']}/{database or c['database']}")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
