# Validation report
_Generated 2026-10-26 03:03:03_

**37 passed · 0 failed · 0 errored · 19 informational**

| Suite | Check | Status | Rows |
|---|---|---|---:|
| 01_reconciliation.sql | `reconcile_row_conservation` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_loader_handoff` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_target_row_counts` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_error_log_vs_audit` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_primary_key_checksum` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_billing_control_total` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconcile_no_id_both_loaded_and_quarantined` | ✅ PASS | 0 |
| 01_reconciliation.sql | `reconciliation_summary` | ℹ️ INFO | 3 |
| 02_referential_integrity.sql | `appointments_without_patient` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `billing_without_appointment` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `billing_without_patient` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `billing_patient_differs_from_appointment_patient` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `merged_patient_ids_still_present` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `merge_survivor_exists` | ✅ PASS | 0 |
| 02_referential_integrity.sql | `patients_with_no_activity` | ℹ️ INFO | 1 |
| 03_data_integrity.sql | `patients_dob_in_future_or_too_old` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_mrn_not_normalised` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_duplicate_mrn_after_normalisation` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_bad_phone_format` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_bad_email_format` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_bad_state_or_postal` | ✅ PASS | 0 |
| 03_data_integrity.sql | `patients_untrimmed_names` | ✅ PASS | 0 |
| 03_data_integrity.sql | `potential_duplicate_patients` | ℹ️ INFO | 0 |
| 03_data_integrity.sql | `appointments_duplicate_slot` | ✅ PASS | 0 |
| 03_data_integrity.sql | `appointments_completed_in_future` | ✅ PASS | 0 |
| 03_data_integrity.sql | `appointments_bad_provider_format` | ✅ PASS | 0 |
| 03_data_integrity.sql | `billing_math_does_not_balance` | ✅ PASS | 0 |
| 03_data_integrity.sql | `billing_bad_invoice_number` | ✅ PASS | 0 |
| 03_data_integrity.sql | `billing_dated_before_appointment` | ✅ PASS | 0 |
| 03_data_integrity.sql | `billing_duplicate_invoice_numbers` | ✅ PASS | 0 |
| 03_data_integrity.sql | `billing_on_cancelled_appointments` | ℹ️ INFO | 1 |
| 03_data_integrity.sql | `completeness_profile_patients` | ℹ️ INFO | 1 |
| 03_data_integrity.sql | `billing_revenue_by_status` | ℹ️ INFO | 6 |
| 04_migration_errors.sql | `load_failures_detected` | ✅ PASS | 0 |
| 04_migration_errors.sql | `audit_rows_missing` | ✅ PASS | 0 |
| 04_migration_errors.sql | `sequences_out_of_sync` | ✅ PASS | 0 |
| 04_migration_errors.sql | `unparseable_values_leaked_through` | ✅ PASS | 0 |
| 04_migration_errors.sql | `merge_targets_missing` | ✅ PASS | 0 |
| 04_migration_errors.sql | `error_summary_by_type` | ℹ️ INFO | 9 |
| 04_migration_errors.sql | `cascade_rejections` | ℹ️ INFO | 2 |
| 04_migration_errors.sql | `quarantined_money_at_risk` | ℹ️ INFO | 1 |
| 04_migration_errors.sql | `rejected_sample` | ℹ️ INFO | 10 |
| 05_source_mysql_profile.sql | `source_row_counts` | ℹ️ INFO | 3 |
| 05_source_mysql_profile.sql | `source_duplicate_mrns` | ℹ️ INFO | 15 |
| 05_source_mysql_profile.sql | `source_orphan_appointments` | ℹ️ INFO | 1 |
| 05_source_mysql_profile.sql | `source_orphan_billing` | ℹ️ INFO | 1 |
| 05_source_mysql_profile.sql | `source_billing_math_errors` | ℹ️ INFO | 1 |
| 05_source_mysql_profile.sql | `source_null_profile_patients` | ℹ️ INFO | 1 |
| 05_source_mysql_profile.sql | `source_gender_inventory` | ℹ️ INFO | 8 |
| 05_source_mysql_profile.sql | `source_appointment_status_inventory` | ℹ️ INFO | 16 |
| 05_source_mysql_profile.sql | `source_dob_format_inventory` | ℹ️ INFO | 5 |
| cross_db | `mysql_source_count_equals_audit_source_rows` | ✅ PASS | 0 |
| cross_db | `billing_money_is_conserved` | ✅ PASS | 0 |
| cross_db | `no_mrn_invented_in_target` | ✅ PASS | 0 |
| cross_db | `no_mrn_silently_lost` | ✅ PASS | 0 |
| cross_db | `target_patients_not_more_than_distinct_source_mrns` | ✅ PASS | 0 |

### reconciliation_summary — INFO
_one-line-per-table migration scorecard_

| table_name   |   source_rows |   loaded_rows |   duplicates_merged |   rejected_rows |   load_failures |   pct_loaded |   load_seconds |
|:-------------|--------------:|--------------:|--------------------:|----------------:|----------------:|-------------:|---------------:|
| patients     |          2100 |          1965 |                  99 |              36 |               0 |         93.6 |           0.49 |
| appointments |          6242 |          5877 |                 177 |             188 |               0 |         94.2 |           0.94 |
| billing      |          4509 |          4270 |                  85 |             154 |               0 |         94.7 |           0.72 |

### patients_with_no_activity — INFO
_patients with neither appointments nor invoices (informational; normal for new registrations)_

|   patients_without_appointments |
|--------------------------------:|
|                             141 |

### potential_duplicate_patients — INFO
_same name + DOB under different MRNs (needs human review, not auto-merged)_

_no rows returned_

### billing_on_cancelled_appointments — INFO
_invoices attached to CANCELLED appointments (business review item)_

|   invoices_on_cancelled_appointments |
|-------------------------------------:|
|                                    0 |

### completeness_profile_patients — INFO
_how complete are optional patient attributes after cleaning?_

|   patients |   pct_phone |   pct_email |   pct_address |   pct_gender_known |   pct_blood_type_known |
|-----------:|------------:|------------:|--------------:|-------------------:|-----------------------:|
|       1965 |        78.1 |        88.5 |          95.9 |               95.8 |                   76.4 |

### billing_revenue_by_status — INFO
_sanity view of loaded revenue by payment status_

| status      |   invoices |   total_billed |   insurance_paid |   patient_share |
|:------------|-----------:|---------------:|-----------------:|----------------:|
| PAID        |       2324 |       319676   |        187276    |       132400    |
| PENDING     |        804 |       109346   |         62659    |        46686.9  |
| PARTIAL     |        514 |        71310   |         41084.9  |        30225.1  |
| DENIED      |        344 |        46440.7 |         26043    |        20397.7  |
| WRITTEN_OFF |        199 |        25973.5 |         16132.3  |         9841.2  |
| UNKNOWN     |         85 |        10593.5 |          6021.91 |         4571.58 |

### error_summary_by_type — INFO
_what was rejected / merged, and why_

| table_name   | error_category   | error_type                 |   rows |
|:-------------|:-----------------|:---------------------------|-------:|
| appointments | MERGED_DUPLICATE | duplicate_appointment_slot |    177 |
| appointments | REJECTED         | orphan_patient_id          |    188 |
| billing      | MERGED_DUPLICATE | duplicate_invoice_number   |     85 |
| billing      | REJECTED         | orphan_appointment_id      |    135 |
| billing      | REJECTED         | negative_total_amount      |     19 |
| patients     | MERGED_DUPLICATE | duplicate_mrn              |     99 |
| patients     | REJECTED         | missing_date_of_birth      |     23 |
| patients     | REJECTED         | missing_mrn                |      8 |
| patients     | REJECTED         | missing_name               |      5 |

### cascade_rejections — INFO
_appointments/invoices rejected only because their PARENT was rejected (fix the parent to recover them)_

| cascade                 |   rows |
|:------------------------|-------:|
| appointments -> patient |    127 |
| billing -> appointment  |     91 |

### quarantined_money_at_risk — INFO
_billed amount sitting in quarantine (rejected invoices) - finance should review_

|   rejected_invoices |   positive_amount_rejected |
|--------------------:|---------------------------:|
|                 154 |                    19090.7 |

### rejected_sample — INFO
_first 10 rejected rows with their raw payload, for triage_

| table_name   |   source_id | error_type            | raw_record_preview                                                                                                                           |
|:-------------|------------:|:----------------------|:---------------------------------------------------------------------------------------------------------------------------------------------|
| patients     |         155 | missing_mrn           | {"dob": "2008-05-27", "mrn": null, "city": "East Sydneychester", "email": "robert.trujillo93@yahoo.com", "phone": "504.699.0139", "state": " |
| patients     |         247 | missing_date_of_birth | {"dob": null, "mrn": "MRN100247", "city": "Greeneshire", "email": "alison.williams86@outlook.com", "phone": "860-993-5387", "state": "SC", " |
| patients     |         363 | missing_name          | {"dob": "2006-11-13", "mrn": "  mrn100363 ", "city": "Mclaughlinshire", "email": "holly.thompson70@yahoo.com", "phone": "563-926-4957", "sta |
| patients     |         380 | missing_date_of_birth | {"dob": null, "mrn": "  mrn100380 ", "city": "West David", "email": "tammy.mendoza54@example.org", "phone": "+1 543 010 7139", "state": "DC" |
| patients     |         390 | missing_mrn           | {"dob": "2020-07-24", "mrn": null, "city": "Alvarezburgh", "email": "AMANDA.THOMPSON61@GMAIL.COM", "phone": "+1 414 958 7020", "state": "NY" |
| patients     |         429 | missing_date_of_birth | {"dob": null, "mrn": "MRN100429", "city": "Lake Michael", "email": "andrew.garcia54@yahoo.com", "phone": null, "state": "GU", "gender": "Mal |
| patients     |         433 | missing_date_of_birth | {"dob": null, "mrn": "MRN100433", "city": "Roweport", "email": "aimee.ramirez56@yahoo.com", "phone": "597.740.6335", "state": "co", "gender" |
| patients     |         583 | missing_name          | {"dob": "1978-01-05", "mrn": "MRN100583", "city": "New Williamberg", "email": "bruce.cooper64@example.org", "phone": "(360) 324-8413", "stat |
| patients     |         602 | missing_date_of_birth | {"dob": null, "mrn": "MRN100602", "city": "Elizabethview", "email": "kaitlyn.williams5@outlook.com", "phone": "7875066", "state": "mn", "gen |
| patients     |         603 | missing_date_of_birth | {"dob": null, "mrn": "MRN100603", "city": "Howardland", "email": "adam.gomez83@example.org", "phone": "924-399-2011", "state": "ID", "gender |

### source_row_counts — INFO
_control totals on the source_

| table_name   |   row_count |
|:-------------|------------:|
| patients     |        2100 |
| appointments |        6242 |
| billing      |        4509 |

### source_duplicate_mrns — INFO
_patients sharing an MRN (case/space-insensitive)_

| mrn       |   copies | patient_ids   |
|:----------|---------:|:--------------|
| MRN100004 |        2 | 4,2023        |
| MRN100025 |        2 | 25,2009       |
| MRN100030 |        2 | 30,2006       |
| MRN100036 |        2 | 36,2007       |
| MRN100037 |        2 | 37,2100       |
| MRN100040 |        2 | 40,2046       |
| MRN100051 |        2 | 51,2036       |
| MRN100065 |        2 | 65,2047       |
| MRN100069 |        2 | 69,2029       |
| MRN100097 |        2 | 97,2024       |
| MRN100113 |        2 | 113,2079      |
| MRN100122 |        2 | 122,2071      |
| MRN100175 |        2 | 175,2064      |
| MRN100180 |        2 | 180,2055      |
| MRN100212 |        2 | 212,2002      |

### source_orphan_appointments — INFO
_appointments whose patient_id does not exist (no FK in legacy schema)_

|   orphan_appointments |
|----------------------:|
|                    61 |

### source_orphan_billing — INFO
_invoices whose appointment_id does not exist_

|   orphan_invoices |
|------------------:|
|                44 |

### source_billing_math_errors — INFO
_invoices where total <> insurance_paid + patient_responsibility, or amounts missing/negative_

|   negative_total |   missing_insurance_paid |   missing_patient_share |   split_does_not_add_up |
|-----------------:|-------------------------:|------------------------:|------------------------:|
|               19 |                      178 |                     128 |                     120 |

### source_null_profile_patients — INFO
_missing values per patient column_

|   total |   null_mrn |   null_dob |   null_gender |   null_phone |   null_email |   null_blood_type |
|--------:|-----------:|-----------:|--------------:|-------------:|-------------:|------------------:|
|    2100 |          8 |         26 |            91 |          163 |          218 |               412 |

### source_gender_inventory — INFO
_every spelling of gender in use_

| gender   |   n |
|:---------|----:|
| Female   | 612 |
| Male     | 552 |
| F        | 426 |
| m        | 364 |
| <NULL>   |  91 |
| other    |  25 |
| X        |  15 |
| O        |  15 |

### source_appointment_status_inventory — INFO
_every spelling of appointment status in use_

| status    |    n |
|:----------|-----:|
| Completed | 2128 |
| complete  |  730 |
| attended  |  726 |
| Done      |  694 |
| cancelled |  495 |
| SCHEDULED |  264 |
| cxl       |  179 |
| canceled  |  168 |
| <NULL>    |  122 |
| NO_SHOW   |  119 |
| confirmed |  117 |
| noshow    |  105 |
| DNA       |  103 |
| Booked    |  101 |
| No Show   |  101 |
| no-show   |   90 |

### source_dob_format_inventory — INFO
_date-of-birth format patterns in the free-text column_

| dob_format   |    n |
|:-------------|-----:|
| YYYY-MM-DD   | 1281 |
| MM/DD/YYYY   |  408 |
| DD-Mon-YYYY  |  195 |
| YYYY/MM/DD   |  190 |
| <NULL>       |   26 |
