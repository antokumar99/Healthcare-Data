"""TRANSFORM: handle missing values, remove duplicates, standardise formats.

Design principles
-----------------
1. **Nothing disappears silently.** Every source row ends in exactly one of:
   clean (loaded) | merged duplicate | rejected.  Merged/rejected rows are returned
   with their full raw payload so migrate.py can quarantine them in PostgreSQL.
2. **Fix what is safely fixable, reject what is not.**  Optional attributes get
   standardised or defaulted; missing *required* keys (MRN, DOB, invoice number,
   etc.) or broken references are rejected rather than invented.
3. **Referential integrity is preserved through de-duplication.**  When duplicate
   patients/appointments are merged, children are re-pointed to the survivor.
4. **Cleaning is deterministic and idempotent** - same input, same output.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schema_mapping import COLUMN_MAP, PK, TARGET_COLUMNS

log = logging.getLogger("cleaning")

NULL_TOKENS = {"", "n/a", "na", "null", "none", "nan", "unknown", "-", "?"}
DOB_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d"]
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
VALID_BLOOD = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}

GENDER_MAP = {"m": "M", "male": "M", "f": "F", "female": "F",
              "o": "O", "other": "O", "x": "O", "nonbinary": "O", "nonbinary ": "O"}
APPT_STATUS_MAP = {
    "scheduled": "SCHEDULED", "booked": "SCHEDULED", "confirmed": "SCHEDULED",
    "completed": "COMPLETED", "complete": "COMPLETED", "done": "COMPLETED", "attended": "COMPLETED",
    "cancelled": "CANCELLED", "canceled": "CANCELLED", "cxl": "CANCELLED",
    "noshow": "NO_SHOW", "dna": "NO_SHOW",
}
PAY_STATUS_MAP = {
    "paid": "PAID", "p": "PAID", "pending": "PENDING", "open": "PENDING",
    "partial": "PARTIAL", "partiallypaid": "PARTIAL", "denied": "DENIED", "rejected": "DENIED",
    "writtenoff": "WRITTEN_OFF", "writeoff": "WRITTEN_OFF",
}


# --------------------------------------------------------------------------- result container
@dataclass
class CleanResult:
    table: str
    source_rows: int
    clean: pd.DataFrame
    rejects: pd.DataFrame
    duplicates: pd.DataFrame
    id_map: dict
    corrections: Counter = field(default_factory=Counter)

    @property
    def summary(self) -> dict:
        return dict(table=self.table, source_rows=self.source_rows, clean_rows=len(self.clean),
                    duplicates_merged=len(self.duplicates), rejected=len(self.rejects))


# --------------------------------------------------------------------------- generic helpers
def _json_default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def _error_frame(raw: pd.DataFrame, index, pk: str, error_type, message) -> pd.DataFrame:
    """Build quarantine rows (source id + full raw payload) for the given raw-row labels."""
    index = list(index)
    types = error_type if not isinstance(error_type, str) else [error_type] * len(index)
    msgs = message if not isinstance(message, str) else [message] * len(index)
    recs = raw.loc[index].to_dict("records")
    payloads = [json.dumps({k: (None if pd.isna(v) else v) for k, v in r.items()}, default=_json_default)
                for r in recs]
    return pd.DataFrame({"source_id": raw.loc[index, pk].tolist(), "error_type": list(types),
                         "error_message": list(msgs), "raw_record": payloads})


def _empty_errors() -> pd.DataFrame:
    return pd.DataFrame(columns=["source_id", "error_type", "error_message", "raw_record"])


def _prepare(raw: pd.DataFrame, table: str) -> pd.DataFrame:
    """Rename to target names, strip whitespace, turn placeholder tokens into real NULLs."""
    df = raw.rename(columns=COLUMN_MAP[table]).copy()
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(
                lambda v: None if isinstance(v, str) and re.sub(r"\s+", " ", v.strip()).lower() in NULL_TOKENS
                else re.sub(r"\s+", " ", v.strip()) if isinstance(v, str) else v)
    return df


def _track(corr: Counter, field_: str, before: pd.Series, after: pd.Series) -> None:
    b_na, a_na = before.isna(), after.isna()
    changed = (~b_na & ~a_na & (before.astype(str) != after.astype(str))).sum()
    nulled = (~b_na & a_na).sum()
    filled = (b_na & ~a_na).sum()
    if changed:
        corr[(field_, "standardized")] += int(changed)
    if nulled:
        corr[(field_, "invalid_set_to_null")] += int(nulled)
    if filled:
        corr[(field_, "missing_filled_with_default")] += int(filled)


def _apply(df, col, fn, corr):
    before = df[col]
    after = before.map(fn)
    _track(corr, col, before, after)
    df[col] = after


def smart_title(v):
    """Title-case only when the value is ALL CAPS / all lower (keeps McDonald, O'Brien)."""
    if not isinstance(v, str):
        return None
    return v.title() if v.isupper() or v.islower() else v


def parse_dates(series: pd.Series, formats=DOB_FORMATS) -> pd.Series:
    s = series.astype("object").where(series.notna(), None)
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in formats:
        todo = out.isna() & s.notna()
        if not todo.any():
            break
        out.loc[todo] = pd.to_datetime(s[todo].astype(str), format=fmt, errors="coerce")
    return out


def norm_phone(v):
    if not isinstance(v, str):
        return None
    d = re.sub(r"\D", "", v)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"{d[:3]}-{d[3:6]}-{d[6:]}" if len(d) == 10 else None


def norm_zip(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    m = re.fullmatch(r"(\d{1,5})(-\d{4})?", str(v).strip())
    return (m.group(1).zfill(5) + (m.group(2) or "")) if m else None


def norm_provider(v):
    if not isinstance(v, str):
        return None
    name = re.sub(r"^\s*dr\.?\s+", "", v.strip(), flags=re.I)
    return "Dr. " + smart_title(re.sub(r"\s+", " ", name))


def _status_key(v):
    return re.sub(r"[\s_\-]+", "", v.lower()) if isinstance(v, str) else None


class _Flagger:
    """Collects the *first* validation failure per row."""

    def __init__(self, index):
        self.type = pd.Series(None, index=index, dtype=object)
        self.msg = pd.Series(None, index=index, dtype=object)

    def flag(self, mask: pd.Series, error_type: str, message: str):
        m = mask.fillna(False) & self.type.isna()
        self.type[m] = error_type
        self.msg[m] = message

    @property
    def bad(self) -> pd.Series:
        return self.type.notna()


# --------------------------------------------------------------------------- PATIENTS
PATIENT_OPTIONAL = ["gender", "phone", "email", "address_line", "city", "state_code",
                    "postal_code", "blood_type"]


def clean_patients(raw: pd.DataFrame, now: pd.Timestamp | None = None) -> CleanResult:
    now = now or pd.Timestamp.now()
    corr: Counter = Counter()
    df = _prepare(raw, "patients")
    raw = raw.copy()
    raw.index = df.index

    _apply(df, "mrn", lambda v: v.upper() if isinstance(v, str) else None, corr)
    _apply(df, "first_name", smart_title, corr)
    _apply(df, "last_name", smart_title, corr)
    _apply(df, "gender", lambda v: GENDER_MAP.get(_status_key(v)) if isinstance(v, str) else None, corr)
    _apply(df, "phone", norm_phone, corr)
    _apply(df, "email", lambda v: v.lower() if isinstance(v, str) and EMAIL_RE.match(v.lower()) else None, corr)
    _apply(df, "state_code", lambda v: v.upper() if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{2}", v) else None, corr)
    _apply(df, "postal_code", norm_zip, corr)
    _apply(df, "blood_type", lambda v: v.upper() if isinstance(v, str) and v.upper() in VALID_BLOOD else None, corr)
    for c in ("address_line", "city"):
        _apply(df, c, smart_title if c == "city" else (lambda v: v if isinstance(v, str) else None), corr)

    dob_raw = df["date_of_birth"]
    dob = parse_dates(dob_raw)
    non_iso = dob_raw.notna() & dob.notna() & ~dob_raw.astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    if non_iso.any():
        corr[("date_of_birth", "standardized")] += int(non_iso.sum())
    df["date_of_birth"] = dob

    is_active = pd.to_numeric(df["is_active"], errors="coerce")
    corr[("is_active", "missing_filled_with_default")] += int(is_active.isna().sum())
    df["is_active"] = is_active.fillna(1).astype(int).astype(bool)
    created = pd.to_datetime(df["created_at"], errors="coerce")
    corr[("created_at", "missing_filled_with_default")] += int(created.isna().sum())
    df["created_at"] = created.fillna(now)

    # ---- validation (required fields)
    f = _Flagger(df.index)
    f.flag(df["mrn"].isna(), "missing_mrn", "MRN is required (natural key)")
    f.flag(df["first_name"].isna() | df["last_name"].isna(), "missing_name", "first/last name required")
    f.flag(dob_raw.isna(), "missing_date_of_birth", "date of birth is required")
    f.flag(dob.isna(), "unparseable_date_of_birth", "date of birth not in a recognised format")
    f.flag((dob > now) | (dob < now - pd.DateOffset(years=120)), "dob_out_of_range", "DOB in the future or >120 years ago")

    # ---- de-duplication on MRN, with survivorship (most complete record wins)
    valid = df[~f.bad].copy()
    valid["_score"] = valid[PATIENT_OPTIONAL].notna().sum(axis=1)
    valid = valid.sort_values(["_score", "patient_id"], ascending=[False, True])
    survivors = valid.drop_duplicates("mrn", keep="first").set_index("mrn")
    best = valid.groupby("mrn")[PATIENT_OPTIONAL].first()      # first non-null per column
    for col in PATIENT_OPTIONAL:
        gap = survivors[col].isna() & best[col].reindex(survivors.index).notna()
        if gap.any():
            survivors.loc[gap, col] = best[col].reindex(survivors.index)[gap]
            corr[(col, "filled_from_duplicate_record")] += int(gap.sum())
    mrn_to_id = survivors["patient_id"].to_dict()
    survivors = survivors.reset_index().drop(columns="_score").sort_values("patient_id")
    survivor_ids = set(survivors["patient_id"])

    id_map, dup_idx, rej_idx = {}, [], []
    for idx, pid, mrn in zip(df.index, df["patient_id"], df["mrn"]):
        if pid in survivor_ids:
            id_map[int(pid)] = int(pid)
        elif isinstance(mrn, str) and mrn in mrn_to_id:     # same MRN as a surviving row => duplicate
            id_map[int(pid)] = int(mrn_to_id[mrn])
            dup_idx.append(idx)
        else:
            rej_idx.append(idx)

    duplicates = _error_frame(raw, dup_idx, "patient_id", "duplicate_mrn", [
        f"merged into patient_id={id_map[int(df.at[i, 'patient_id'])]} (same MRN)" for i in dup_idx]) \
        if dup_idx else _empty_errors()
    rejects = _error_frame(raw, rej_idx, "patient_id", f.type[rej_idx].tolist(), f.msg[rej_idx].tolist()) \
        if rej_idx else _empty_errors()

    # ---- defaults applied *after* survivorship so duplicates can fill the gaps first
    for col, default in (("gender", "U"), ("blood_type", "UNKNOWN")):
        corr[(col, "missing_filled_with_default")] += int(survivors[col].isna().sum())
        survivors[col] = survivors[col].fillna(default)
    survivors["date_of_birth"] = survivors["date_of_birth"].dt.date
    clean = survivors[TARGET_COLUMNS["patients"]].reset_index(drop=True)
    return CleanResult("patients", len(raw), clean, rejects, duplicates, id_map, corr)


# --------------------------------------------------------------------------- APPOINTMENTS
def _dedupe(df: pd.DataFrame, keys: list[str], pk: str, valid_mask: pd.Series):
    """Keep the lowest pk per key. Returns (survivors, duplicate_index, {dup_pk: survivor_pk})."""
    v = df[valid_mask].sort_values(pk)
    is_dup = v.duplicated(keys, keep="first")
    survivors, dups = v[~is_dup], v[is_dup]
    mapping = {int(p): int(p) for p in survivors[pk]}
    if len(dups):
        merged = dups[keys + [pk]].merge(survivors[keys + [pk]], on=keys, suffixes=("", "_surv"))
        mapping.update({int(a): int(b) for a, b in zip(merged[pk], merged[pk + "_surv"])})
    return survivors, list(dups.index), mapping


def clean_appointments(raw: pd.DataFrame, patient_map: dict, now: pd.Timestamp | None = None) -> CleanResult:
    now = now or pd.Timestamp.now()
    corr: Counter = Counter()
    df = _prepare(raw, "appointments")
    raw = raw.copy()
    raw.index = df.index

    src_pid = pd.to_numeric(df["patient_id"], errors="coerce")
    df["patient_id"] = src_pid.map(patient_map)                         # re-point to surviving patient
    n_repointed = int(((df["patient_id"] != src_pid) & df["patient_id"].notna()).sum())
    if n_repointed:
        corr[("patient_id", "re-pointed_to_surviving_patient")] += n_repointed

    df["scheduled_at"] = pd.to_datetime(df["scheduled_at"], errors="coerce")
    _apply(df, "provider_name", norm_provider, corr)
    corr[("provider_name", "missing_filled_with_default")] += int(df["provider_name"].isna().sum())
    df["provider_name"] = df["provider_name"].fillna("Unassigned")
    _apply(df, "department", smart_title, corr)
    corr[("department", "missing_filled_with_default")] += int(df["department"].isna().sum())
    df["department"] = df["department"].fillna("General Medicine")
    st = df["status"].map(lambda v: APPT_STATUS_MAP.get(_status_key(v)))
    corr[("status", "standardized")] += int((st.notna() & (st != df["status"])).sum())
    corr[("status", "missing_or_unmapped_set_to_UNKNOWN")] += int(st.isna().sum())
    df["status"] = st.fillna("UNKNOWN")
    dur = pd.to_numeric(df["duration_minutes"], errors="coerce")
    bad_dur = dur.isna() | ~dur.between(5, 480)
    corr[("duration_minutes", "missing_or_invalid_set_to_30")] += int(bad_dur.sum())
    df["duration_minutes"] = dur.where(~bad_dur, 30).astype(int)
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce").fillna(df["scheduled_at"])

    f = _Flagger(df.index)
    f.flag(df["patient_id"].isna(), "orphan_patient_id", "patient does not exist in cleaned patients")
    f.flag(df["scheduled_at"].isna(), "missing_scheduled_at", "appointment datetime is required")

    df["patient_id"] = df["patient_id"].astype("Int64")
    survivors, dup_idx, id_map = _dedupe(df, ["patient_id", "scheduled_at", "provider_name"],
                                         "appointment_id", ~f.bad)
    rej_idx = list(df.index[f.bad])
    duplicates = _error_frame(raw, dup_idx, "appointment_id", "duplicate_appointment_slot", [
        f"merged into appointment_id={id_map[int(df.at[i, 'appointment_id'])]} (same patient/time/provider)"
        for i in dup_idx]) if dup_idx else _empty_errors()
    rejects = _error_frame(raw, rej_idx, "appointment_id", f.type[rej_idx].tolist(), f.msg[rej_idx].tolist()) \
        if rej_idx else _empty_errors()
    clean = survivors[TARGET_COLUMNS["appointments"]].astype({"patient_id": int}).reset_index(drop=True)
    return CleanResult("appointments", len(raw), clean, rejects, duplicates, id_map, corr)


# --------------------------------------------------------------------------- BILLING
def clean_billing(raw: pd.DataFrame, patient_map: dict, appt_map: dict, appts_clean: pd.DataFrame) -> CleanResult:
    corr: Counter = Counter()
    df = _prepare(raw, "billing")
    raw = raw.copy()
    raw.index = df.index
    appt_lookup = appts_clean.set_index("appointment_id")[["patient_id", "scheduled_at"]]

    src_appt = pd.to_numeric(df["appointment_id"], errors="coerce")
    df["appointment_id"] = src_appt.map(appt_map)
    src_pid = pd.to_numeric(df["patient_id"], errors="coerce")
    appt_patient = df["appointment_id"].map(appt_lookup["patient_id"])
    new_pid = src_pid.map(patient_map).where(src_pid.notna(), appt_patient)
    if (src_pid.isna() & appt_patient.notna()).any():
        corr[("patient_id", "missing_filled_from_appointment")] += int((src_pid.isna() & appt_patient.notna()).sum())
    df["patient_id"] = new_pid

    _apply(df, "invoice_number", lambda v: v.upper() if isinstance(v, str) else None, corr)
    _apply(df, "cpt_code", lambda v: v.upper() if isinstance(v, str) else None, corr)
    _apply(df, "payer_name", lambda v: v if isinstance(v, str) else None, corr)
    corr[("payer_name", "missing_filled_with_default")] += int(df["payer_name"].isna().sum())
    df["payer_name"] = df["payer_name"].fillna("Self-Pay")
    st = df["status"].map(lambda v: PAY_STATUS_MAP.get(_status_key(v)))
    corr[("status", "standardized")] += int((st.notna() & (st != df["status"])).sum())
    corr[("status", "missing_or_unmapped_set_to_UNKNOWN")] += int(st.isna().sum())
    df["status"] = st.fillna("UNKNOWN")

    total = pd.to_numeric(df["total_amount"], errors="coerce")
    ins = pd.to_numeric(df["insurance_paid"], errors="coerce")
    pat = pd.to_numeric(df["patient_responsibility"], errors="coerce")
    # money: infer a missing insurance_paid from the patient share when possible, else assume 0
    infer_ins = ins.isna() & pat.notna() & total.notna() & ((total - pat) >= -0.005)
    corr[("insurance_paid", "missing_inferred_from_total_minus_patient_share")] += int(infer_ins.sum())
    ins = ins.where(~infer_ins, (total - pat).clip(lower=0))
    corr[("insurance_paid", "missing_filled_with_default")] += int(ins.isna().sum())
    ins = ins.fillna(0.0)
    corr[("patient_responsibility", "missing_recomputed")] += int(pat.isna().sum())
    expected_pat = (total - ins).round(2)
    mismatch = pat.notna() & ((pat - expected_pat).abs() > 0.005) & total.notna()
    corr[("patient_responsibility", "inconsistent_recomputed")] += int(mismatch.sum())
    pat = pat.where(pat.notna() & ~mismatch, expected_pat)
    df["total_amount"], df["insurance_paid"], df["patient_responsibility"] = total.round(2), ins.round(2), pat.round(2)

    inv_date = parse_dates(df["invoice_date"].astype("object").where(df["invoice_date"].notna(), None),
                           ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d"])
    fallback = df["appointment_id"].map(appt_lookup["scheduled_at"]).dt.normalize()
    corr[("invoice_date", "missing_filled_from_appointment_date")] += int((inv_date.isna() & fallback.notna()).sum())
    df["invoice_date"] = inv_date.fillna(fallback)

    f = _Flagger(df.index)
    f.flag(df["appointment_id"].isna(), "orphan_appointment_id", "appointment does not exist in cleaned appointments")
    f.flag(df["patient_id"].isna() | (df["patient_id"] != appt_patient), "patient_appointment_mismatch",
           "billing patient differs from appointment patient")
    f.flag(df["invoice_number"].isna(), "missing_invoice_number", "invoice number is required")
    f.flag(df["total_amount"].isna(), "missing_total_amount", "total amount is required")
    f.flag(df["total_amount"] < 0, "negative_total_amount", "total amount cannot be negative")
    f.flag((df["insurance_paid"] < 0) | (df["patient_responsibility"] < -0.005), "invalid_payment_split",
           "insurance paid exceeds total or split is negative")

    df["appointment_id"] = df["appointment_id"].astype("Int64")
    df["patient_id"] = df["patient_id"].astype("Int64")
    survivors, dup_idx, id_map = _dedupe(df, ["invoice_number"], "billing_id", ~f.bad)
    rej_idx = list(df.index[f.bad])
    duplicates = _error_frame(raw, dup_idx, "billing_id", "duplicate_invoice_number", [
        f"merged into billing_id={id_map[int(df.at[i, 'billing_id'])]} (same invoice number)"
        for i in dup_idx]) if dup_idx else _empty_errors()
    rejects = _error_frame(raw, rej_idx, "billing_id", f.type[rej_idx].tolist(), f.msg[rej_idx].tolist()) \
        if rej_idx else _empty_errors()
    clean = survivors[TARGET_COLUMNS["billing"]].astype({"appointment_id": int, "patient_id": int}).copy()
    clean["invoice_date"] = clean["invoice_date"].dt.date
    clean["patient_responsibility"] = clean["patient_responsibility"].clip(lower=0)
    return CleanResult("billing", len(raw), clean.reset_index(drop=True), rejects, duplicates, id_map, corr)


# --------------------------------------------------------------------------- orchestration
def clean_all(raw: dict[str, pd.DataFrame]) -> dict[str, CleanResult]:
    pat = clean_patients(raw["patients"])
    appt = clean_appointments(raw["appointments"], pat.id_map)
    bill = clean_billing(raw["billing"], pat.id_map, appt.id_map, appt.clean)
    out = {"patients": pat, "appointments": appt, "billing": bill}
    for r in out.values():
        log.info("cleaned %-13s source=%5d clean=%5d merged=%4d rejected=%4d",
                 r.table, r.source_rows, len(r.clean), len(r.duplicates), len(r.rejects))
    return out


def cleaning_report_markdown(results: dict[str, CleanResult]) -> str:
    lines = ["# Cleaning report", "", "## Row accounting", "",
             "| Table | Source rows | Clean (to load) | Duplicates merged | Rejected |", "|---|---:|---:|---:|---:|"]
    for r in results.values():
        s = r.summary
        lines.append(f"| {s['table']} | {s['source_rows']} | {s['clean_rows']} | {s['duplicates_merged']} | {s['rejected']} |")
    lines += ["", "## Corrections applied", "", "| Table | Field | Action | Rows |", "|---|---|---|---:|"]
    for r in results.values():
        for (fld, action), n in sorted(r.corrections.items()):
            if n:
                lines.append(f"| {r.table} | {fld} | {action} | {n} |")
    lines += ["", "## Rejections by reason", "", "| Table | Reason | Rows |", "|---|---|---:|"]
    for r in results.values():
        for reason, n in r.rejects["error_type"].value_counts().items():
            lines.append(f"| {r.table} | {reason} | {n} |")
    return "\n".join(lines) + "\n"
