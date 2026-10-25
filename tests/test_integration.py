"""Integration tests: need MySQL + PostgreSQL. They use *_test databases so real data is untouched.
Skipped automatically when the servers are not reachable."""
import pytest
from sqlalchemy import text

from healthcare_pipeline import config
from healthcare_pipeline.generate_data import generate_all, write_csvs


def _reachable() -> bool:
    try:
        import psycopg2
        import pymysql
        c = config.MYSQL
        pymysql.connect(host=c["host"], port=c["port"], user=c["user"], password=c["password"]).close()
        p = config.PG
        psycopg2.connect(host=p["host"], port=p["port"], user=p["user"], password=p["password"], dbname="postgres").close()
        return True
    except Exception:                                              # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="MySQL/PostgreSQL not reachable")


@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setitem(config.MYSQL, "database", "healthcare_legacy_test")
    mp.setitem(config.PG, "database", "healthcare_target_test")
    from healthcare_pipeline.load_source import load_source
    from healthcare_pipeline.migrate import run_migration
    raw_dir = tmp_path_factory.mktemp("raw")
    write_csvs(*generate_all(300, seed=11), out_dir=raw_dir)
    load_source(raw_dir)
    summary = run_migration(batch_size=250)                         # small batches => several commits per table
    yield summary
    mp.undo()


def test_full_pipeline_passes_every_validation(migrated, monkeypatch):
    monkeypatch.setitem(config.MYSQL, "database", "healthcare_legacy_test")
    monkeypatch.setitem(config.PG, "database", "healthcare_target_test")
    from healthcare_pipeline.validate import run_validation
    results, ok = run_validation(write_report=False, quiet=True)
    failing = [(r.name, r.status, r.detail) for r in results if r.status in ("FAIL", "ERROR")]
    assert ok, failing


def test_summary_balances(migrated):
    for t in ("patients", "appointments", "billing"):
        s = migrated[t]
        assert s["source_rows"] == s["loaded"] + s["duplicates_merged"] + s["rejected"] + s["load_failures"]
        assert s["load_failures"] == 0


def test_batch_insert_isolates_bad_row(migrated, monkeypatch):
    """A row that violates a DB constraint must be quarantined without losing its batch-mates."""
    import uuid

    import pandas as pd

    monkeypatch.setitem(config.PG, "database", "healthcare_target_test")
    from healthcare_pipeline.db import pg_connect
    from healthcare_pipeline.migrate import batch_insert
    good = dict(mrn="MRNX0", first_name="A", last_name="B", date_of_birth=pd.Timestamp("1990-01-01").date(),
                gender="F", phone=None, email=None, address_line=None, city=None, state_code=None,
                postal_code=None, blood_type="UNKNOWN", is_active=True, created_at=pd.Timestamp("2020-01-01"))
    rows = [{**good, "patient_id": 900001 + i, "mrn": f"MRNX{i}"} for i in range(5)]
    rows[2]["gender"] = "Z"                                         # violates CHECK (gender IN (...))
    conn = pg_connect()
    try:
        run_id = uuid.uuid4()
        loaded, failed = batch_insert(conn, run_id, "patients", pd.DataFrame(rows), batch_size=5)
        assert (loaded, failed) == (4, 1)
        with conn.cursor() as cur:
            cur.execute("SELECT source_id, error_category FROM healthcare.migration_errors WHERE run_id = %s", (str(run_id),))
            assert cur.fetchall() == [(900003, "LOAD_FAILURE")]
    finally:
        conn.close()
