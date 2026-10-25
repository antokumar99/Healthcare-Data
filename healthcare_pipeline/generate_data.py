"""Synthetic healthcare data generator (patients, appointments, billing).

Produces a *deliberately dirty* legacy dataset:
  * mixed date / phone / gender / status formats
  * missing values in optional and a few required fields
  * duplicate patients (same MRN, different surrogate id), duplicate
    appointments and duplicate invoices
  * orphaned appointments / invoices pointing at non-existent parents
  * inconsistent money columns and a few negative amounts

All randomness is seeded, so runs are reproducible.
"""
from __future__ import annotations

import argparse
import logging
import random
from datetime import datetime, timedelta

import pandas as pd
from faker import Faker

from .config import RAW_DIR, SEED, setup_logging

log = logging.getLogger("generate")

DEPARTMENTS = ["Cardiology", "General Medicine", "Pediatrics", "Orthopedics", "Dermatology",
               "Neurology", "Oncology", "Radiology", "Emergency", "Obstetrics"]
REASONS = ["Annual physical", "Follow-up visit", "Chest pain", "Persistent cough", "Back pain",
           "Skin rash", "Headache", "Blood pressure check", "Lab review", "Vaccination",
           "Prenatal checkup", "Knee pain", "Diabetes management", "Allergy consultation"]
INSURERS = ["Blue Cross Blue Shield", "Aetna", "Cigna", "UnitedHealthcare", "Humana",
            "Medicare", "Medicaid", "Kaiser Permanente"]
CPT_RANGES = {"99213": (80, 180), "99214": (120, 260), "99203": (110, 250), "99395": (150, 300),
              "93000": (50, 120), "80053": (30, 90), "71046": (100, 250), "90471": (25, 60)}
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

GENDER_VARIANTS = {
    "M": ["M", "m", "Male", "male", "MALE"],
    "F": ["F", "f", "Female", "female", "FEMALE"],
    "O": ["O", "Other", "other", "X"],
}
APPT_STATUS_VARIANTS = {
    "SCHEDULED": ["Scheduled", "scheduled", "SCHEDULED", "Booked", "confirmed"],
    "COMPLETED": ["Completed", "completed", "COMPLETED", "Done", "complete", "attended"],
    "CANCELLED": ["Cancelled", "canceled", "CANCELLED", "cancelled", "cxl"],
    "NO_SHOW": ["No Show", "no-show", "NO_SHOW", "noshow", "DNA"],
}
PAY_STATUS_VARIANTS = {
    "PAID": ["Paid", "paid", "PAID", "P"],
    "PENDING": ["Pending", "pending", "PENDING", "open"],
    "PARTIAL": ["Partial", "partially paid", "PARTIAL"],
    "DENIED": ["Denied", "denied", "rejected"],
    "WRITTEN_OFF": ["Written Off", "write-off", "WRITTEN_OFF"],
}


# --------------------------------------------------------------------------- helpers
def _blank(rng: random.Random, p: float) -> bool:
    return rng.random() < p


def _fmt_dob(d, rng):
    r = rng.random()
    if r < 0.60:
        return d.strftime("%Y-%m-%d")
    if r < 0.80:
        return d.strftime("%m/%d/%Y")
    if r < 0.90:
        return d.strftime("%d-%b-%Y")
    return d.strftime("%Y/%m/%d")


def _fmt_phone(digits: str, rng):
    a, b, c = digits[:3], digits[3:6], digits[6:]
    style = rng.randrange(6)
    return [f"({a}) {b}-{c}", f"{a}-{b}-{c}", digits, f"+1 {a} {b} {c}", f"{a}.{b}.{c}",
            digits[:7]][style]  # style 5 = truncated / invalid


def _dirty_patient(base: dict, rng: random.Random, fake: Faker) -> dict:
    """Turn a clean patient dict into a legacy-style dirty row."""
    r = dict(base)
    r["dob"] = None if _blank(rng, 0.015) else _fmt_dob(base["dob"], rng)
    r["gender"] = None if _blank(rng, 0.04) else rng.choice(GENDER_VARIANTS[base["gender"]])
    r["phone"] = None if _blank(rng, 0.08) else _fmt_phone(base["phone"], rng)
    r["email"] = None if _blank(rng, 0.10) else (
        base["email"].upper() if rng.random() < 0.05 else
        base["email"].replace("@", "") if rng.random() < 0.02 else base["email"])
    r["address"] = None if _blank(rng, 0.05) else base["address"]
    r["city"] = None if _blank(rng, 0.03) else base["city"]
    r["state"] = None if _blank(rng, 0.03) else (base["state"].lower() if rng.random() < 0.1 else base["state"])
    r["zip_code"] = None if _blank(rng, 0.05) else base["zip_code"].lstrip("0")  # lost leading zeros
    r["blood_type"] = None if _blank(rng, 0.20) else (
        rng.choice(["N/A", "unknown", base["blood_type"].lower()]) if rng.random() < 0.1 else base["blood_type"])
    r["mrn"] = None if _blank(rng, 0.005) else (
        f"  {base['mrn'].lower()} " if rng.random() < 0.05 else base["mrn"])
    r["first_name"] = None if _blank(rng, 0.003) else (
        base["first_name"].upper() if rng.random() < 0.08 else
        base["first_name"].lower() if rng.random() < 0.04 else f" {base['first_name']} ")
    r["last_name"] = base["last_name"].upper() if rng.random() < 0.08 else base["last_name"]
    r["is_active"] = 1 if rng.random() < 0.93 else 0
    return r


# --------------------------------------------------------------------------- generators
def generate_all(n_patients: int = 2000, seed: int = SEED, dup_rate: float = 0.05):
    """Return (patients, appointments, billing) DataFrames in *legacy* shape."""
    rng = random.Random(seed)
    _DOCTOR_POOL.clear()
    Faker.seed(seed)
    fake = Faker("en_US")
    now = datetime.now().replace(microsecond=0)

    # ---------------- patients
    base_patients = []
    for pid in range(1, n_patients + 1):
        gender = rng.choices(["M", "F", "O"], weights=[48, 49, 3])[0]
        first = fake.first_name_male() if gender == "M" else fake.first_name_female() if gender == "F" else fake.first_name()
        last = fake.last_name()
        base_patients.append(dict(
            patient_id=pid, mrn=f"MRN{100000 + pid}", first_name=first, last_name=last,
            dob=fake.date_of_birth(minimum_age=0, maximum_age=95), gender=gender,
            phone="".join(str(rng.randint(2, 9) if i == 0 else rng.randint(0, 9)) for i in range(10)),
            email=f"{first}.{last}{rng.randint(1, 99)}@{rng.choice(['gmail.com', 'yahoo.com', 'outlook.com', 'example.org'])}".lower().replace("'", ""),
            address=fake.street_address(), city=fake.city(), state=fake.state_abbr(),
            zip_code=fake.postcode(), blood_type=rng.choice(BLOOD_TYPES), is_active=1,
            created_at=(now - timedelta(days=rng.randint(30, 1800), seconds=rng.randint(0, 86399))),
        ))

    rows = [_dirty_patient(b, rng, fake) for b in base_patients]

    # duplicates: same person re-registered under a new surrogate id
    dup_map: dict[int, int] = {}      # original id -> duplicate id
    next_id = n_patients + 1
    for b in rng.sample(base_patients, int(n_patients * dup_rate)):
        d = _dirty_patient(b, rng, fake)
        d["patient_id"] = next_id
        d["created_at"] = b["created_at"] + timedelta(days=rng.randint(1, 200))
        rows.append(d)
        dup_map[b["patient_id"]] = next_id
        next_id += 1
    patients = pd.DataFrame(rows)

    # ---------------- appointments
    appts = []
    appt_id = 1
    for b in base_patients:
        for _ in range(rng.choices(range(0, 8), weights=[8, 15, 22, 20, 15, 10, 6, 4])[0]):
            when = now + timedelta(days=rng.randint(-730, 60), hours=rng.randint(-8, 8))
            when = when.replace(minute=rng.choice([0, 15, 30, 45]), second=0)
            if when < now:
                true_status = rng.choices(["COMPLETED", "CANCELLED", "NO_SHOW"], weights=[75, 15, 10])[0]
            else:
                true_status = "SCHEDULED"
            pid = dup_map[b["patient_id"]] if b["patient_id"] in dup_map and rng.random() < 0.5 else b["patient_id"]
            appts.append(dict(
                appointment_id=appt_id, patient_id=pid,
                doctor_name=None if _blank(rng, 0.03) else _pick_doctor(fake, rng),
                department=None if _blank(rng, 0.02) else rng.choice(DEPARTMENTS),
                appointment_datetime=when,
                status=None if _blank(rng, 0.02) else rng.choice(APPT_STATUS_VARIANTS[true_status]),
                reason=None if _blank(rng, 0.10) else rng.choice(REASONS),
                duration_minutes=None if _blank(rng, 0.05) else rng.choice([15, 30, 30, 45, 60]),
                created_at=when - timedelta(days=rng.randint(1, 45)),
                _true_status=true_status,
            ))
            appt_id += 1

    # duplicated appointments (identical slot, new id)
    for a in rng.sample(appts, int(len(appts) * 0.03)):
        d = dict(a)
        d["appointment_id"] = appt_id
        appts.append(d)
        appt_id += 1
    # orphans: patient never existed
    for a in rng.sample(appts, max(1, int(len(appts) * 0.01))):
        d = dict(a)
        d["appointment_id"] = appt_id
        d["patient_id"] = n_patients + 10_000 + appt_id
        d["appointment_datetime"] = a["appointment_datetime"] + timedelta(days=1)  # not a duplicate slot
        appts.append(d)
        appt_id += 1
    appointments = pd.DataFrame(appts)

    # ---------------- billing
    bills = []
    bill_id = 1
    inv = 10_000_000
    for a in [x for x in appts if x["_true_status"] in ("COMPLETED", "NO_SHOW") and x["patient_id"] < n_patients + 10_000]:
        if rng.random() > 0.9:
            continue
        cpt = rng.choice(list(CPT_RANGES))
        lo, hi = CPT_RANGES[cpt]
        total = round(rng.uniform(lo, hi), 2)
        insurer = rng.choice(INSURERS + ["Self-Pay"] * 2)
        ins_paid = 0.0 if insurer == "Self-Pay" else round(total * rng.choice([0.5, 0.7, 0.8, 0.9]), 2)
        pat = round(total - ins_paid, 2)
        pay_status = rng.choices(list(PAY_STATUS_VARIANTS), weights=[55, 20, 12, 8, 5])[0]
        inv += rng.randint(1, 9)
        invoice = f"INV-{inv}"
        row = dict(
            billing_id=bill_id, appointment_id=a["appointment_id"], patient_id=a["patient_id"],
            invoice_number=f" {invoice.lower()}" if rng.random() < 0.03 else invoice,
            service_code=None if _blank(rng, 0.02) else cpt,
            total_amount=total, insurance_paid=None if _blank(rng, 0.04) else ins_paid,
            patient_responsibility=None if _blank(rng, 0.03) else pat,
            insurance_provider=None if (insurer == "Self-Pay" and rng.random() < 0.7) or _blank(rng, 0.03) else insurer,
            payment_status=None if _blank(rng, 0.02) else rng.choice(PAY_STATUS_VARIANTS[pay_status]),
            billing_date=(a["appointment_datetime"] + timedelta(days=rng.randint(0, 30))).date()
            if not _blank(rng, 0.02) else None,
        )
        if rng.random() < 0.02:        # money doesn't add up
            row["patient_responsibility"] = round(pat + rng.choice([5.0, 10.0, -3.5]), 2)
        if rng.random() < 0.005:       # negative amount (data entry error)
            row["total_amount"] = -abs(total)
        bills.append(row)
        bill_id += 1

    for b in rng.sample(bills, int(len(bills) * 0.02)):         # duplicate invoices
        d = dict(b)
        d["billing_id"] = bill_id
        bills.append(d)
        bill_id += 1
    for b in rng.sample(bills, max(1, int(len(bills) * 0.01))):  # orphan invoices
        d = dict(b)
        d["billing_id"] = bill_id
        d["appointment_id"] = 900_000 + bill_id
        d["invoice_number"] = f"INV-{inv + bill_id}"
        bills.append(d)
        bill_id += 1
    billing = pd.DataFrame(bills)

    appointments = appointments.drop(columns="_true_status")
    patients = patients[["patient_id", "mrn", "first_name", "last_name", "dob", "gender", "phone", "email",
                         "address", "city", "state", "zip_code", "blood_type", "is_active", "created_at"]]
    return patients, appointments, billing


_DOCTOR_POOL: list[str] = []


def _pick_doctor(fake: Faker, rng: random.Random) -> str:
    """Pick from a small stable pool of providers, with messy prefix/casing variants."""
    if not _DOCTOR_POOL:
        _DOCTOR_POOL.extend(f"{fake.first_name()} {fake.last_name()}" for _ in range(40))
    name = rng.choice(_DOCTOR_POOL)
    r = rng.random()
    if r < 0.75:
        return f"Dr. {name}"
    if r < 0.85:
        return f"dr. {name.lower()}"
    if r < 0.93:
        return f"DR. {name.upper()}"
    return f"Dr {name}"


def write_csvs(patients, appointments, billing, out_dir=RAW_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in (("patients", patients), ("appointments", appointments), ("billing", billing)):
        df.to_csv(out_dir / f"{name}.csv", index=False)
        log.info("wrote %-13s %6d rows -> %s", name, len(df), out_dir / f"{name}.csv")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate dirty synthetic healthcare data")
    ap.add_argument("--patients", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    setup_logging()
    write_csvs(*generate_all(args.patients, args.seed))


if __name__ == "__main__":
    main()
