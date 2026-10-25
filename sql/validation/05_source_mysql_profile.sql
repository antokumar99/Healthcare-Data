-- ============================================================================
-- 05  SOURCE PROFILING (MySQL legacy database)
-- Run BEFORE migrating to understand what the cleaner has to deal with.
-- All informational.
-- ============================================================================

-- name: source_row_counts
-- description: control totals on the source
-- expect: info
SELECT 'patients' AS table_name, COUNT(*) AS row_count FROM patients
UNION ALL SELECT 'appointments', COUNT(*) FROM appointments
UNION ALL SELECT 'billing', COUNT(*) FROM billing;

-- name: source_duplicate_mrns
-- description: patients sharing an MRN (case/space-insensitive)
-- expect: info
SELECT UPPER(TRIM(mrn)) AS mrn, COUNT(*) AS copies, GROUP_CONCAT(patient_id ORDER BY patient_id) AS patient_ids
FROM patients WHERE mrn IS NOT NULL
GROUP BY UPPER(TRIM(mrn)) HAVING COUNT(*) > 1
ORDER BY copies DESC, mrn LIMIT 15;

-- name: source_orphan_appointments
-- description: appointments whose patient_id does not exist (no FK in legacy schema)
-- expect: info
SELECT COUNT(*) AS orphan_appointments
FROM appointments a LEFT JOIN patients p ON p.patient_id = a.patient_id
WHERE p.patient_id IS NULL;

-- name: source_orphan_billing
-- description: invoices whose appointment_id does not exist
-- expect: info
SELECT COUNT(*) AS orphan_invoices
FROM billing b LEFT JOIN appointments a ON a.appointment_id = b.appointment_id
WHERE a.appointment_id IS NULL;

-- name: source_billing_math_errors
-- description: invoices where total <> insurance_paid + patient_responsibility, or amounts missing/negative
-- expect: info
SELECT SUM(total_amount < 0)                                                    AS negative_total,
       SUM(insurance_paid IS NULL)                                              AS missing_insurance_paid,
       SUM(patient_responsibility IS NULL)                                      AS missing_patient_share,
       SUM(insurance_paid IS NOT NULL AND patient_responsibility IS NOT NULL
           AND ABS(total_amount - insurance_paid - patient_responsibility) > 0.005) AS split_does_not_add_up
FROM billing;

-- name: source_null_profile_patients
-- description: missing values per patient column
-- expect: info
SELECT COUNT(*) AS total,
       SUM(mrn IS NULL) AS null_mrn, SUM(dob IS NULL) AS null_dob, SUM(gender IS NULL) AS null_gender,
       SUM(phone IS NULL) AS null_phone, SUM(email IS NULL) AS null_email,
       SUM(blood_type IS NULL) AS null_blood_type
FROM patients;

-- name: source_gender_inventory
-- description: every spelling of gender in use
-- expect: info
SELECT COALESCE(gender, '<NULL>') AS gender, COUNT(*) AS n FROM patients GROUP BY gender ORDER BY n DESC;

-- name: source_appointment_status_inventory
-- description: every spelling of appointment status in use
-- expect: info
SELECT COALESCE(status, '<NULL>') AS status, COUNT(*) AS n FROM appointments GROUP BY status ORDER BY n DESC;

-- name: source_dob_format_inventory
-- description: date-of-birth format patterns in the free-text column
-- expect: info
SELECT CASE WHEN dob IS NULL THEN '<NULL>'
            WHEN dob REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 'YYYY-MM-DD'
            WHEN dob REGEXP '^[0-9]{2}/[0-9]{2}/[0-9]{4}$' THEN 'MM/DD/YYYY'
            WHEN dob REGEXP '^[0-9]{2}-[A-Za-z]{3}-[0-9]{4}$' THEN 'DD-Mon-YYYY'
            WHEN dob REGEXP '^[0-9]{4}/[0-9]{2}/[0-9]{2}$' THEN 'YYYY/MM/DD'
            ELSE 'OTHER' END AS dob_format, COUNT(*) AS n
FROM patients GROUP BY 1 ORDER BY n DESC;
