"""Unit tests for the transform stage. No database required."""
import re

import pandas as pd
import pytest

from healthcare_pipeline.cleaning import (clean_all, clean_patients, norm_phone, norm_provider, norm_zip,
                                          parse_dates, smart_title)
from healthcare_pipeline.generate_data import generate_all
from healthcare_pipeline.migrate import id_checksum, to_records


@pytest.fixture(scope="module")
def raw():
    p, a, b = generate_all(400, seed=7)
    return {"patients": p, "appointments": a, "billing": b}


@pytest.fixture(scope="module")
def cleaned(raw):
    return clean_all(raw)


# ----------------------------------------------------------------- helpers
@pytest.mark.parametrize("value,expected", [
    ("(555) 123-4567", "555-123-4567"), ("5551234567", "555-123-4567"), ("+1 555 123 4567", "555-123-4567"),
    ("555.123.4567", "555-123-4567"), ("1234567", None), (None, None)])
def test_norm_phone(value, expected):
    assert norm_phone(value) == expected


def test_parse_dates_handles_all_legacy_formats():
    s = pd.Series(["2001-02-03", "02/03/2001", "03-Feb-2001", "2001/02/03", "garbage", None])
    out = parse_dates(s)
    assert list(out.iloc[:4]) == [pd.Timestamp("2001-02-03")] * 4
    assert out.iloc[4:].isna().all()


@pytest.mark.parametrize("value,expected", [("4921", "04921"), ("12345", "12345"), ("12345-6789", "12345-6789"),
                                            ("abc", None), (None, None)])
def test_norm_zip(value, expected):
    assert norm_zip(value) == expected


def test_smart_title_preserves_mixed_case():
    assert smart_title("MCDONALD") == "Mcdonald"
    assert smart_title("McDonald") == "McDonald"
    assert smart_title("o'brien") == "O'Brien"


def test_norm_provider():
    assert norm_provider("DR. JANE ROE") == "Dr. Jane Roe"
    assert norm_provider("dr jane roe") == "Dr. Jane Roe"
    assert norm_provider("Jane Roe") == "Dr. Jane Roe"


# ----------------------------------------------------------------- invariants
def test_every_source_row_is_accounted_for(cleaned):
    for r in cleaned.values():
        assert r.source_rows == len(r.clean) + len(r.duplicates) + len(r.rejects), r.table


def test_patients_unique_and_normalised(cleaned):
    p = cleaned["patients"].clean
    assert p["mrn"].is_unique
    assert (p["mrn"] == p["mrn"].str.upper().str.strip()).all()
    assert set(p["gender"]) <= {"M", "F", "O", "U"}
    assert p["phone"].dropna().map(lambda v: bool(re.fullmatch(r"\d{3}-\d{3}-\d{4}", v))).all()
    assert p["date_of_birth"].notna().all()
    assert p["state_code"].dropna().str.fullmatch(r"[A-Z]{2}").all()


def test_no_orphans_after_cleaning(cleaned):
    pat, app, bil = (cleaned[t].clean for t in ("patients", "appointments", "billing"))
    assert app["patient_id"].isin(pat["patient_id"]).all()
    assert bil["appointment_id"].isin(app["appointment_id"]).all()
    assert bil["patient_id"].isin(pat["patient_id"]).all()
    merged = app.merge(bil, on="appointment_id", suffixes=("_a", "_b"))
    assert (merged["patient_id_a"] == merged["patient_id_b"]).all()


def test_appointments_deduplicated(cleaned):
    a = cleaned["appointments"].clean
    assert not a.duplicated(["patient_id", "scheduled_at", "provider_name"]).any()
    assert set(a["status"]) <= {"SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW", "UNKNOWN"}
    assert a["duration_minutes"].between(5, 480).all()


def test_billing_math_and_uniqueness(cleaned):
    b = cleaned["billing"].clean
    assert b["invoice_number"].is_unique
    assert ((b["total_amount"] - b["insurance_paid"] - b["patient_responsibility"]).abs() < 0.005).all()
    assert (b["total_amount"] >= 0).all()
    assert set(b["status"]) <= {"PAID", "PENDING", "PARTIAL", "DENIED", "WRITTEN_OFF", "UNKNOWN"}


def test_id_map_points_at_surviving_ids(cleaned):
    for r in cleaned.values():
        survivors = set(r.clean.iloc[:, 0])
        assert set(r.id_map.values()) <= survivors


def test_cleaning_is_deterministic(raw):
    now = pd.Timestamp("2026-01-01")
    a = clean_patients(raw["patients"], now=now).clean
    b = clean_patients(raw["patients"], now=now).clean
    pd.testing.assert_frame_equal(a, b)


def test_duplicate_patient_fills_gaps_from_other_copy():
    raw = pd.DataFrame([
        dict(patient_id=1, mrn="MRN1", first_name="Ann", last_name="Lee", dob="1990-01-01", gender="F", phone=None,
             email=None, address="1 Main St", city="X", state="NY", zip_code="10001", blood_type=None, is_active=1,
             created_at="2020-01-01"),
        dict(patient_id=2, mrn=" mrn1 ", first_name="ANN", last_name="LEE", dob="01/01/1990", gender=None,
             phone="(555) 111-2222", email="ann@x.org", address=None, city=None, state=None, zip_code=None,
             blood_type="O+", is_active=1, created_at="2020-02-01")])
    res = clean_patients(raw)
    assert len(res.clean) == 1 and len(res.duplicates) == 1 and res.id_map == {1: 1, 2: 1}
    row = res.clean.iloc[0]
    assert row["phone"] == "555-111-2222" and row["email"] == "ann@x.org" and row["blood_type"] == "O+"
    assert row["address_line"] == "1 Main St"                      # kept from the survivor


def test_rejects_carry_full_raw_payload(cleaned):
    rej = cleaned["patients"].rejects
    assert len(rej) > 0
    import json
    payload = json.loads(rej.iloc[0]["raw_record"])
    assert "patient_id" in payload and "dob" in payload             # raw column names preserved


# ----------------------------------------------------------------- loader helpers
def test_to_records_converts_money_to_decimal_and_nan_to_none():
    from decimal import Decimal
    df = pd.DataFrame({"total_amount": [10.1], "city": [float("nan")]})
    assert to_records(df, ["total_amount", "city"]) == [(Decimal("10.10"), None)]


def test_id_checksum_is_order_independent():
    assert id_checksum([3, 1, 2]) == id_checksum([1, 2, 3])
