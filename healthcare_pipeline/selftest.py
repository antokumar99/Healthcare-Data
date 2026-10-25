"""SELF-TEST: prove the validation suite can actually *detect* corruption.

For each fault we (1) re-run the migration to get a known-good target, (2) corrupt
PostgreSQL in one specific way, (3) run the validators, and (4) assert that the
checks we expect to fire did fire.  A validator that has never been seen to fail is
not a validator.
"""
from __future__ import annotations

import logging

try:
    from sqlalchemy import text  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    text = None  # type: ignore[assignment]
from tabulate import tabulate

from .db import pg_engine
from .migrate import run_migration
from .validate import run_validation

log = logging.getLogger("selftest")
MIN = lambda t, pk: f"(SELECT MIN({pk}) FROM healthcare.{t})"  # noqa: E731

FAULTS = [
    ("delete one invoice",
     [f"DELETE FROM healthcare.billing WHERE billing_id = {MIN('billing', 'billing_id')}"],
     {"reconcile_target_row_counts", "reconcile_primary_key_checksum", "reconcile_billing_control_total",
      "billing_money_is_conserved"}),
    ("silently inflate one invoice (+$10, still balances)",
     [f"UPDATE healthcare.billing SET total_amount = total_amount + 10, patient_responsibility = patient_responsibility + 10 "
      f"WHERE billing_id = {MIN('billing', 'billing_id')}"],
     {"reconcile_billing_control_total", "billing_money_is_conserved"}),
    ("insert orphan appointment (FKs bypassed)",
     ["SET LOCAL session_replication_role = replica",
      "INSERT INTO healthcare.appointments (patient_id, provider_name, department, scheduled_at, status, duration_minutes) "
      "VALUES (99999999, 'Dr. Ghost', 'General Medicine', now() - interval '1 day', 'COMPLETED', 30)"],
     {"appointments_without_patient", "reconcile_target_row_counts", "reconcile_primary_key_checksum"}),
    ("corrupt a phone number",
     ["UPDATE healthcare.patients SET phone = '555-12' WHERE patient_id = "
      "(SELECT MIN(patient_id) FROM healthcare.patients WHERE phone IS NOT NULL)"],
     {"patients_bad_phone_format"}),
    ("un-normalise an MRN",
     [f"UPDATE healthcare.patients SET mrn = lower(mrn) WHERE patient_id = {MIN('patients', 'patient_id')}"],
     {"patients_mrn_not_normalised", "no_mrn_invented_in_target"}),
    ("inject a LOAD_FAILURE into the error log",
     ["INSERT INTO healthcare.migration_errors (run_id, table_name, source_id, error_category, error_type, error_message, raw_record) "
      "SELECT run_id, 'billing', 1, 'LOAD_FAILURE', 'IntegrityError', 'simulated', jsonb_build_object('x', 1) FROM healthcare.migration_audit LIMIT 1"],
     {"load_failures_detected", "reconcile_error_log_vs_audit"}),
    ("rewind an identity sequence",
     ["SELECT setval(pg_get_serial_sequence('healthcare.patients', 'patient_id'), 1)"],
     {"sequences_out_of_sync"}),
    ("mark a future appointment COMPLETED",
     ["UPDATE healthcare.appointments SET scheduled_at = now() + interval '30 days', status = 'COMPLETED' "
      f"WHERE appointment_id = {MIN('appointments', 'appointment_id')}"],
     {"appointments_completed_in_future"}),
    ("delete a rejected INVOICE from quarantine (money vanishes)",
     ["DELETE FROM healthcare.migration_errors WHERE error_id = (SELECT MIN(error_id) FROM healthcare.migration_errors "
      "WHERE table_name = 'billing' AND error_category = 'REJECTED' AND CAST(raw_record ->> 'total_amount' AS NUMERIC) > 0)"],
     {"reconcile_error_log_vs_audit", "billing_money_is_conserved"}),
    ("delete a rejected PATIENT from quarantine (patient vanishes)",
     ["DELETE FROM healthcare.migration_errors WHERE error_id = (SELECT MIN(error_id) FROM healthcare.migration_errors "
      "WHERE table_name = 'patients' AND error_type = 'missing_date_of_birth')"],
     {"reconcile_error_log_vs_audit", "no_mrn_silently_lost"}),
]


def run_selftest(batch_size: int = 1000) -> bool:
    eng = pg_engine()
    rows, all_ok = [], True
    for name, statements, expected in FAULTS:
        run_migration(batch_size)                                   # known-good baseline
        baseline, base_ok = run_validation(include_source_profile=False, write_report=False, quiet=True)
        assert base_ok, "baseline migration must be clean before injecting faults"
        try:
            with eng.begin() as conn:
                for st in statements:
                    conn.execute(text(st))
        except Exception as exc:                                    # noqa: BLE001
            rows.append([name, "-", "SKIPPED", str(exc).splitlines()[0][:60]])
            continue
        results, _ = run_validation(include_source_profile=False, write_report=False, quiet=True)
        failed = {r.name for r in results if r.status in ("FAIL", "ERROR")}
        missed = expected - failed
        all_ok &= not missed
        rows.append([name, ", ".join(sorted(expected & failed)) or "-",
                     "DETECTED" if not missed else "MISSED", ", ".join(sorted(missed))])
        log.info("fault %-52s -> %s", name, "detected" if not missed else f"MISSED {missed}")
    run_migration(batch_size)                                       # leave the target in a clean state
    print("\n" + tabulate(rows, headers=["injected fault", "checks that fired", "result", "notes"], tablefmt="github"))
    return all_ok
