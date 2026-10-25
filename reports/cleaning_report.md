# Cleaning report

## Row accounting

| Table | Source rows | Clean (to load) | Duplicates merged | Rejected |
|---|---:|---:|---:|---:|
| patients | 2100 | 1965 | 99 | 36 |
| appointments | 6242 | 5877 | 177 | 188 |
| billing | 4509 | 4270 | 85 | 154 |

## Corrections applied

| Table | Field | Action | Rows |
|---|---|---|---:|
| patients | address_line | filled_from_duplicate_record | 4 |
| patients | blood_type | filled_from_duplicate_record | 10 |
| patients | blood_type | missing_filled_with_default | 463 |
| patients | blood_type | standardized | 55 |
| patients | date_of_birth | standardized | 793 |
| patients | email | filled_from_duplicate_record | 3 |
| patients | email | invalid_set_to_null | 31 |
| patients | email | standardized | 96 |
| patients | first_name | standardized | 217 |
| patients | gender | filled_from_duplicate_record | 2 |
| patients | gender | missing_filled_with_default | 82 |
| patients | gender | standardized | 1601 |
| patients | last_name | standardized | 176 |
| patients | mrn | standardized | 108 |
| patients | phone | filled_from_duplicate_record | 3 |
| patients | phone | invalid_set_to_null | 312 |
| patients | phone | standardized | 1313 |
| patients | postal_code | standardized | 212 |
| patients | state_code | standardized | 238 |
| appointments | department | missing_filled_with_default | 136 |
| appointments | duration_minutes | missing_or_invalid_set_to_30 | 305 |
| appointments | patient_id | re-pointed_to_surviving_patient | 141 |
| appointments | provider_name | missing_filled_with_default | 162 |
| appointments | provider_name | standardized | 1509 |
| appointments | status | missing_or_unmapped_set_to_UNKNOWN | 122 |
| appointments | status | standardized | 5084 |
| billing | insurance_paid | missing_filled_with_default | 5 |
| billing | insurance_paid | missing_inferred_from_total_minus_patient_share | 173 |
| billing | invoice_date | missing_filled_from_appointment_date | 88 |
| billing | invoice_number | standardized | 111 |
| billing | patient_responsibility | inconsistent_recomputed | 121 |
| billing | patient_responsibility | missing_recomputed | 128 |
| billing | payer_name | missing_filled_with_default | 761 |
| billing | status | missing_or_unmapped_set_to_UNKNOWN | 87 |
| billing | status | standardized | 3343 |

## Rejections by reason

| Table | Reason | Rows |
|---|---|---:|
| patients | missing_date_of_birth | 23 |
| patients | missing_mrn | 8 |
| patients | missing_name | 5 |
| appointments | orphan_patient_id | 188 |
| billing | orphan_appointment_id | 135 |
| billing | negative_total_amount | 19 |
