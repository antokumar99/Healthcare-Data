-- ============================================================================
-- 02  REFERENTIAL INTEGRITY (PostgreSQL target)
-- FKs are enforced by the database, but these checks prove it independently
-- (e.g. after a bulk load with triggers/constraints disabled) and also test
-- cross-table business rules that an FK cannot express.
-- ============================================================================

-- name: appointments_without_patient
-- description: every appointment must reference an existing patient
-- expect: zero_rows
SELECT a.appointment_id, a.patient_id
FROM healthcare.appointments a
LEFT JOIN healthcare.patients p ON p.patient_id = a.patient_id
WHERE p.patient_id IS NULL;

-- name: billing_without_appointment
-- description: every invoice must reference an existing appointment
-- expect: zero_rows
SELECT b.billing_id, b.appointment_id
FROM healthcare.billing b
LEFT JOIN healthcare.appointments a ON a.appointment_id = b.appointment_id
WHERE a.appointment_id IS NULL;

-- name: billing_without_patient
-- description: every invoice must reference an existing patient
-- expect: zero_rows
SELECT b.billing_id, b.patient_id
FROM healthcare.billing b
LEFT JOIN healthcare.patients p ON p.patient_id = b.patient_id
WHERE p.patient_id IS NULL;

-- name: billing_patient_differs_from_appointment_patient
-- description: invoice.patient_id must equal the patient of the appointment it bills
-- expect: zero_rows
SELECT b.billing_id, b.patient_id AS billing_patient, a.patient_id AS appointment_patient
FROM healthcare.billing b
JOIN healthcare.appointments a ON a.appointment_id = b.appointment_id
WHERE b.patient_id <> a.patient_id;

-- name: merged_patient_ids_still_present
-- description: patient ids that were merged away as duplicates must not exist in the target
-- expect: zero_rows
SELECT e.source_id AS merged_patient_id
FROM healthcare.migration_errors e
JOIN healthcare.patients p ON p.patient_id = e.source_id
WHERE e.table_name = 'patients' AND e.error_category = 'MERGED_DUPLICATE';

-- name: merge_survivor_exists
-- description: every "merged into <table>_id=N" message must point at a row that exists in the target
-- expect: zero_rows
SELECT e.table_name, e.source_id, e.error_message
FROM healthcare.migration_errors e
WHERE e.error_category = 'MERGED_DUPLICATE'
  AND NOT EXISTS (
        SELECT 1 FROM healthcare.patients p
        WHERE e.table_name = 'patients'
          AND p.patient_id = CAST(substring(e.error_message FROM 'patient_id=([0-9]+)') AS INTEGER))
  AND NOT EXISTS (
        SELECT 1 FROM healthcare.appointments a
        WHERE e.table_name = 'appointments'
          AND a.appointment_id = CAST(substring(e.error_message FROM 'appointment_id=([0-9]+)') AS INTEGER))
  AND NOT EXISTS (
        SELECT 1 FROM healthcare.billing b
        WHERE e.table_name = 'billing'
          AND b.billing_id = CAST(substring(e.error_message FROM 'billing_id=([0-9]+)') AS INTEGER));

-- name: patients_with_no_activity
-- description: patients with neither appointments nor invoices (informational; normal for new registrations)
-- expect: info
SELECT COUNT(*) AS patients_without_appointments
FROM healthcare.patients p
WHERE NOT EXISTS (SELECT 1 FROM healthcare.appointments a WHERE a.patient_id = p.patient_id);
