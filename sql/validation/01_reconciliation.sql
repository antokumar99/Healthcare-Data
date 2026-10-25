-- ============================================================================
-- 01  RECORD RECONCILIATION  (PostgreSQL target)
-- Conservation law for every table:
--   source_rows = loaded_rows + load_failures + duplicates_merged + rejected_rows
-- Every query marked "expect: zero_rows" returns ONLY violations.
-- ============================================================================

-- name: reconcile_row_conservation
-- description: source rows must be fully accounted for (loaded + merged + rejected + failed)
-- expect: zero_rows
SELECT table_name, source_rows,
       loaded_rows + load_failures + duplicates_merged + rejected_rows AS accounted_for,
       source_rows - (loaded_rows + load_failures + duplicates_merged + rejected_rows) AS unaccounted
FROM healthcare.migration_audit
WHERE source_rows <> loaded_rows + load_failures + duplicates_merged + rejected_rows;

-- name: reconcile_loader_handoff
-- description: rows handed to the loader must equal rows loaded + rows PostgreSQL refused
-- expect: zero_rows
SELECT table_name, expected_load_rows, loaded_rows, load_failures
FROM healthcare.migration_audit
WHERE expected_load_rows <> loaded_rows + load_failures;

-- name: reconcile_target_row_counts
-- description: actual COUNT(*) in each target table must equal the audit's loaded_rows
-- expect: zero_rows
SELECT a.table_name, a.loaded_rows AS audit_loaded, t.actual_rows
FROM healthcare.migration_audit a
JOIN (SELECT 'patients' AS table_name, COUNT(*) AS actual_rows FROM healthcare.patients
      UNION ALL SELECT 'appointments', COUNT(*) FROM healthcare.appointments
      UNION ALL SELECT 'billing', COUNT(*) FROM healthcare.billing) t USING (table_name)
WHERE a.loaded_rows <> t.actual_rows;

-- name: reconcile_error_log_vs_audit
-- description: quarantine table counts must match the audit counters
-- expect: zero_rows
SELECT a.table_name,
       a.rejected_rows, COALESCE(e.rejected, 0)  AS logged_rejected,
       a.duplicates_merged, COALESCE(e.merged, 0) AS logged_merged,
       a.load_failures, COALESCE(e.failed, 0)     AS logged_failed
FROM healthcare.migration_audit a
LEFT JOIN (SELECT table_name,
                  COUNT(*) FILTER (WHERE error_category = 'REJECTED')         AS rejected,
                  COUNT(*) FILTER (WHERE error_category = 'MERGED_DUPLICATE') AS merged,
                  COUNT(*) FILTER (WHERE error_category = 'LOAD_FAILURE')     AS failed
           FROM healthcare.migration_errors GROUP BY table_name) e USING (table_name)
WHERE a.rejected_rows <> COALESCE(e.rejected, 0)
   OR a.duplicates_merged <> COALESCE(e.merged, 0)
   OR a.load_failures <> COALESCE(e.failed, 0);

-- name: reconcile_primary_key_checksum
-- description: md5 of the sorted primary keys in the target must equal the checksum computed before loading
-- expect: zero_rows
SELECT a.table_name, a.expected_id_checksum, t.actual_checksum
FROM healthcare.migration_audit a
JOIN (SELECT 'patients' AS table_name, md5(COALESCE(string_agg(patient_id::text, ',' ORDER BY patient_id), '')) AS actual_checksum FROM healthcare.patients
      UNION ALL SELECT 'appointments', md5(COALESCE(string_agg(appointment_id::text, ',' ORDER BY appointment_id), '')) FROM healthcare.appointments
      UNION ALL SELECT 'billing', md5(COALESCE(string_agg(billing_id::text, ',' ORDER BY billing_id), '')) FROM healthcare.billing) t USING (table_name)
WHERE a.expected_id_checksum <> t.actual_checksum;

-- name: reconcile_billing_control_total
-- description: SUM(total_amount) in the target must equal the control total captured before loading
-- expect: zero_rows
SELECT a.expected_amount_sum, b.actual_sum
FROM healthcare.migration_audit a,
     (SELECT COALESCE(SUM(total_amount), 0) AS actual_sum FROM healthcare.billing) b
WHERE a.table_name = 'billing' AND a.expected_amount_sum <> b.actual_sum;

-- name: reconcile_no_id_both_loaded_and_quarantined
-- description: a source id may be loaded OR quarantined, never both
-- expect: zero_rows
SELECT 'patients' AS table_name, e.source_id, e.error_category
FROM healthcare.migration_errors e JOIN healthcare.patients t ON t.patient_id = e.source_id
WHERE e.table_name = 'patients' AND e.error_category <> 'LOAD_FAILURE'
UNION ALL
SELECT 'appointments', e.source_id, e.error_category
FROM healthcare.migration_errors e JOIN healthcare.appointments t ON t.appointment_id = e.source_id
WHERE e.table_name = 'appointments' AND e.error_category <> 'LOAD_FAILURE'
UNION ALL
SELECT 'billing', e.source_id, e.error_category
FROM healthcare.migration_errors e JOIN healthcare.billing t ON t.billing_id = e.source_id
WHERE e.table_name = 'billing' AND e.error_category <> 'LOAD_FAILURE';

-- name: reconciliation_summary
-- description: one-line-per-table migration scorecard
-- expect: info
SELECT table_name, source_rows, loaded_rows, duplicates_merged, rejected_rows, load_failures,
       ROUND(100.0 * loaded_rows / NULLIF(source_rows, 0), 1) AS pct_loaded,
       ROUND(EXTRACT(EPOCH FROM (completed_at - started_at))::numeric, 2) AS load_seconds
FROM healthcare.migration_audit
ORDER BY audit_id;
