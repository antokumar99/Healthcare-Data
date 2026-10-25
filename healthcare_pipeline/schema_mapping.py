"""MySQL -> PostgreSQL schema mapping: the single source of truth.

* COLUMN_MAP drives the renaming performed in cleaning.py
* TARGET_COLUMNS fixes the insert column order used by migrate.py
* MAPPING_ROWS documents type conversions & the rule applied; it is rendered to
  docs/schema_mapping.md on every run.
"""
from __future__ import annotations

COLUMN_MAP = {  # source column -> target column (only where the name changes)
    "patients": {"dob": "date_of_birth", "address": "address_line",
                 "state": "state_code", "zip_code": "postal_code"},
    "appointments": {"appointment_datetime": "scheduled_at", "doctor_name": "provider_name",
                     "reason": "reason_for_visit"},
    "billing": {"service_code": "cpt_code", "insurance_provider": "payer_name",
                "payment_status": "status", "billing_date": "invoice_date"},
}

PK = {"patients": "patient_id", "appointments": "appointment_id", "billing": "billing_id"}

TARGET_COLUMNS = {
    "patients": ["patient_id", "mrn", "first_name", "last_name", "date_of_birth", "gender", "phone",
                 "email", "address_line", "city", "state_code", "postal_code", "blood_type",
                 "is_active", "created_at"],
    "appointments": ["appointment_id", "patient_id", "provider_name", "department", "scheduled_at",
                     "status", "reason_for_visit", "duration_minutes", "created_at"],
    "billing": ["billing_id", "appointment_id", "patient_id", "invoice_number", "cpt_code",
                "total_amount", "insurance_paid", "patient_responsibility", "payer_name", "status",
                "invoice_date"],
}

# (table, source column, source type, target column, target type, transformation rule)
MAPPING_ROWS = [
    ("patients", "patient_id", "INT AUTO_INCREMENT", "patient_id", "INTEGER IDENTITY", "Surviving id kept; sequence reset after load"),
    ("patients", "mrn", "VARCHAR(20)", "mrn", "VARCHAR(20) NOT NULL UNIQUE", "TRIM + UPPER; de-dup key; missing -> reject"),
    ("patients", "first_name / last_name", "VARCHAR(50)", "first_name / last_name", "VARCHAR(50) NOT NULL", "TRIM; title-case if ALL-CAPS/lower; missing -> reject"),
    ("patients", "dob", "VARCHAR(20) mixed formats", "date_of_birth", "DATE NOT NULL", "Parse 4 formats; reject unparseable / future / >120y"),
    ("patients", "gender", "VARCHAR(20)", "gender", "CHAR(1) CHECK(M,F,O,U)", "Value map (male/Female/X...); missing -> 'U'"),
    ("patients", "phone", "VARCHAR(30)", "phone", "VARCHAR(12)", "Digits only -> NNN-NNN-NNNN; invalid -> NULL"),
    ("patients", "email", "VARCHAR(100)", "email", "VARCHAR(100)", "lower-case; regex validate; invalid -> NULL"),
    ("patients", "address", "VARCHAR(200)", "address_line", "VARCHAR(200)", "TRIM"),
    ("patients", "state", "VARCHAR(30)", "state_code", "CHAR(2)", "UPPER; must be 2 letters else NULL"),
    ("patients", "zip_code", "VARCHAR(10)", "postal_code", "VARCHAR(10)", "Left-pad to 5 digits (restores lost leading zeros)"),
    ("patients", "blood_type", "VARCHAR(10)", "blood_type", "VARCHAR(7) CHECK", "UPPER; invalid / missing -> 'UNKNOWN'"),
    ("patients", "is_active", "TINYINT(1)", "is_active", "BOOLEAN", "int -> bool; missing -> TRUE"),
    ("patients", "created_at", "DATETIME", "created_at", "TIMESTAMP", "Direct; missing -> migration time"),
    ("appointments", "patient_id", "INT (no FK)", "patient_id", "INTEGER FK -> patients", "Re-pointed to surviving patient; orphan -> reject"),
    ("appointments", "doctor_name", "VARCHAR(80)", "provider_name", "VARCHAR(80) NOT NULL", "Normalise 'Dr.' prefix/case; missing -> 'Unassigned'"),
    ("appointments", "department", "VARCHAR(60)", "department", "VARCHAR(60) NOT NULL", "TRIM; missing -> 'General Medicine'"),
    ("appointments", "appointment_datetime", "DATETIME", "scheduled_at", "TIMESTAMP NOT NULL", "Missing -> reject"),
    ("appointments", "status", "VARCHAR(20) free text", "status", "VARCHAR(12) CHECK", "Value map -> SCHEDULED/COMPLETED/CANCELLED/NO_SHOW; else UNKNOWN"),
    ("appointments", "reason", "TEXT", "reason_for_visit", "TEXT", "TRIM; missing stays NULL"),
    ("appointments", "duration_minutes", "SMALLINT", "duration_minutes", "SMALLINT CHECK 5..480", "Missing / out of range -> 30"),
    ("appointments", "(patient, datetime, doctor)", "-", "UNIQUE uq_appointment_slot", "-", "Duplicates merged; billing re-pointed to survivor"),
    ("billing", "appointment_id", "INT (no FK)", "appointment_id", "INTEGER FK -> appointments", "Re-pointed to surviving appt; orphan -> reject"),
    ("billing", "patient_id", "INT (no FK)", "patient_id", "INTEGER FK -> patients", "Taken from the appointment; mismatch -> reject"),
    ("billing", "invoice_number", "VARCHAR(30)", "invoice_number", "VARCHAR(30) UNIQUE", "TRIM + UPPER; de-dup key; missing -> reject"),
    ("billing", "service_code", "VARCHAR(10)", "cpt_code", "VARCHAR(10)", "TRIM"),
    ("billing", "total_amount", "DECIMAL(10,2)", "total_amount", "NUMERIC(10,2) CHECK >=0", "Negative / missing -> reject"),
    ("billing", "insurance_paid", "DECIMAL(10,2)", "insurance_paid", "NUMERIC(10,2) NOT NULL", "Missing -> 0.00"),
    ("billing", "patient_responsibility", "DECIMAL(10,2)", "patient_responsibility", "NUMERIC(10,2) NOT NULL", "Missing/inconsistent -> total - insurance_paid"),
    ("billing", "insurance_provider", "VARCHAR(80)", "payer_name", "VARCHAR(80) NOT NULL", "Missing -> 'Self-Pay'"),
    ("billing", "payment_status", "VARCHAR(20) free text", "status", "VARCHAR(12) CHECK", "Value map -> PAID/PENDING/PARTIAL/DENIED/WRITTEN_OFF; else UNKNOWN"),
    ("billing", "billing_date", "DATE", "invoice_date", "DATE NOT NULL", "Missing -> appointment date"),
]


def render_mapping_markdown() -> str:
    lines = ["# MySQL → PostgreSQL schema mapping", "",
             "_Generated by `healthcare_pipeline/schema_mapping.py`_", "",
             "| Table | Source column | Source type | Target column | Target type | Rule |",
             "|---|---|---|---|---|---|"]
    lines += [f"| {' | '.join(r)} |" for r in MAPPING_ROWS]
    return "\n".join(lines) + "\n"
