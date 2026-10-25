-- ============================================================================
-- 04  MIGRATION ERROR DETECTION (PostgreSQL target)
-- ============================================================================

-- name: load_failures_detected
-- description: rows PostgreSQL itself refused during the load (should be none: the cleaner must catch them first)
-- expect: zero_rows
SELECT table_name, source_id, error_type, error_message
FROM healthcare.migration_errors WHERE error_category = 'LOAD_FAILURE'
ORDER BY error_id;

-- name: audit_rows_missing
-- description: each of the 3 tables must have exactly one audit row for the run
-- expect: zero_rows
SELECT t.table_name, COUNT(a.audit_id) AS audit_rows
FROM (VALUES ('patients'), ('appointments'), ('billing')) AS t(table_name)
LEFT JOIN healthcare.migration_audit a USING (table_name)
GROUP BY t.table_name HAVING COUNT(a.audit_id) <> 1;

-- name: sequences_out_of_sync
-- description: identity sequences must be >= MAX(id), otherwise the next INSERT collides
-- expect: zero_rows
SELECT s.sequencename, s.last_value, m.max_id
FROM pg_sequences s
JOIN (SELECT 'patients_patient_id_seq' AS seq, MAX(patient_id) AS max_id FROM healthcare.patients
      UNION ALL SELECT 'appointments_appointment_id_seq', MAX(appointment_id) FROM healthcare.appointments
      UNION ALL SELECT 'billing_billing_id_seq', MAX(billing_id) FROM healthcare.billing) m
     ON m.seq = s.sequencename
WHERE s.schemaname = 'healthcare' AND (s.last_value IS NULL OR s.last_value < m.max_id);

-- name: unparseable_values_leaked_through
-- description: quarantined rows without a payload cannot be investigated or replayed
-- expect: zero_rows
SELECT error_id, table_name, source_id FROM healthcare.migration_errors
WHERE raw_record IS NULL OR raw_record = 'null'::jsonb;

-- name: merge_targets_missing
-- description: merged duplicates whose message does not name a survivor (cannot be traced)
-- expect: zero_rows
SELECT error_id, table_name, source_id, error_message FROM healthcare.migration_errors
WHERE error_category = 'MERGED_DUPLICATE' AND error_message !~ '_id=[0-9]+';

-- name: error_summary_by_type
-- description: what was rejected / merged, and why
-- expect: info
SELECT table_name, error_category, error_type, COUNT(*) AS rows
FROM healthcare.migration_errors
GROUP BY table_name, error_category, error_type
ORDER BY table_name, error_category, rows DESC;

-- name: cascade_rejections
-- description: appointments/invoices rejected only because their PARENT was rejected (fix the parent to recover them)
-- expect: info
SELECT 'appointments -> patient' AS cascade, COUNT(*) AS rows
FROM healthcare.migration_errors c
JOIN healthcare.migration_errors p
  ON p.table_name = 'patients' AND p.error_category = 'REJECTED'
 AND p.source_id = CAST(c.raw_record ->> 'patient_id' AS INTEGER)
WHERE c.table_name = 'appointments' AND c.error_type = 'orphan_patient_id'
UNION ALL
SELECT 'billing -> appointment', COUNT(*)
FROM healthcare.migration_errors c
JOIN healthcare.migration_errors p
  ON p.table_name = 'appointments' AND p.error_category = 'REJECTED'
 AND p.source_id = CAST(c.raw_record ->> 'appointment_id' AS INTEGER)
WHERE c.table_name = 'billing' AND c.error_type = 'orphan_appointment_id';

-- name: quarantined_money_at_risk
-- description: billed amount sitting in quarantine (rejected invoices) - finance should review
-- expect: info
SELECT COUNT(*) AS rejected_invoices,
       COALESCE(SUM(CAST(raw_record ->> 'total_amount' AS NUMERIC)) FILTER (WHERE CAST(raw_record ->> 'total_amount' AS NUMERIC) > 0), 0) AS positive_amount_rejected
FROM healthcare.migration_errors
WHERE table_name = 'billing' AND error_category = 'REJECTED';

-- name: rejected_sample
-- description: first 10 rejected rows with their raw payload, for triage
-- expect: info
SELECT table_name, source_id, error_type, left(raw_record::text, 140) AS raw_record_preview
FROM healthcare.migration_errors WHERE error_category = 'REJECTED'
ORDER BY error_id LIMIT 10;
