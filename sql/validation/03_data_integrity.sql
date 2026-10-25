-- ============================================================================
-- 03  DATA INTEGRITY & QUALITY (PostgreSQL target)
-- "expect: zero_rows" => each query returns violating rows only.
-- ============================================================================

-- name: patients_dob_in_future_or_too_old
-- description: date of birth must be plausible
-- expect: zero_rows
SELECT patient_id, date_of_birth FROM healthcare.patients
WHERE date_of_birth > CURRENT_DATE OR date_of_birth < CURRENT_DATE - INTERVAL '120 years';

-- name: patients_mrn_not_normalised
-- description: MRN must be trimmed and upper-case
-- expect: zero_rows
SELECT patient_id, mrn FROM healthcare.patients WHERE mrn <> upper(btrim(mrn));

-- name: patients_duplicate_mrn_after_normalisation
-- description: no two patients may share an MRN once case/whitespace are ignored
-- expect: zero_rows
SELECT upper(btrim(mrn)) AS mrn, COUNT(*) AS n FROM healthcare.patients
GROUP BY 1 HAVING COUNT(*) > 1;

-- name: patients_bad_phone_format
-- description: phone must be NNN-NNN-NNNN or NULL
-- expect: zero_rows
SELECT patient_id, phone FROM healthcare.patients
WHERE phone IS NOT NULL AND phone !~ '^[0-9]{3}-[0-9]{3}-[0-9]{4}$';

-- name: patients_bad_email_format
-- description: email must look like an address and be lower-case, or be NULL
-- expect: zero_rows
SELECT patient_id, email FROM healthcare.patients
WHERE email IS NOT NULL AND (email !~ '^[a-z0-9._%+-]+@[a-z0-9.-]+[.][a-z]{2,}$');

-- name: patients_bad_state_or_postal
-- description: state_code = 2 upper-case letters; postal_code = 5 digits (+4 optional)
-- expect: zero_rows
SELECT patient_id, state_code, postal_code FROM healthcare.patients
WHERE (state_code IS NOT NULL AND state_code !~ '^[A-Z]{2}$')
   OR (postal_code IS NOT NULL AND postal_code !~ '^[0-9]{5}(-[0-9]{4})?$');

-- name: patients_untrimmed_names
-- description: names must have no leading/trailing/double spaces
-- expect: zero_rows
SELECT patient_id, first_name, last_name FROM healthcare.patients
WHERE first_name <> btrim(first_name) OR last_name <> btrim(last_name)
   OR first_name ~ '  ' OR last_name ~ '  ';

-- name: potential_duplicate_patients
-- description: same name + DOB under different MRNs (needs human review, not auto-merged)
-- expect: info
SELECT lower(first_name) AS first_name, lower(last_name) AS last_name, date_of_birth,
       COUNT(*) AS n, string_agg(mrn, ', ' ORDER BY mrn) AS mrns
FROM healthcare.patients
GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;

-- name: appointments_duplicate_slot
-- description: same patient + time + provider must be unique
-- expect: zero_rows
SELECT patient_id, scheduled_at, provider_name, COUNT(*) AS n
FROM healthcare.appointments GROUP BY 1, 2, 3 HAVING COUNT(*) > 1;

-- name: appointments_completed_in_future
-- description: a COMPLETED appointment cannot be scheduled in the future
-- expect: zero_rows
SELECT appointment_id, scheduled_at, status FROM healthcare.appointments
WHERE status = 'COMPLETED' AND scheduled_at > now();

-- name: appointments_bad_provider_format
-- description: provider must be 'Dr. <Name>' or 'Unassigned'
-- expect: zero_rows
SELECT appointment_id, provider_name FROM healthcare.appointments
WHERE provider_name <> 'Unassigned' AND provider_name !~ '^Dr[.] ';

-- name: billing_math_does_not_balance
-- description: total = insurance_paid + patient_responsibility on every invoice
-- expect: zero_rows
SELECT billing_id, total_amount, insurance_paid, patient_responsibility
FROM healthcare.billing WHERE total_amount <> insurance_paid + patient_responsibility;

-- name: billing_bad_invoice_number
-- description: invoice numbers must be INV-<digits>, upper-case, trimmed
-- expect: zero_rows
SELECT billing_id, invoice_number FROM healthcare.billing WHERE invoice_number !~ '^INV-[0-9]+$';

-- name: billing_dated_before_appointment
-- description: an invoice cannot be dated before the visit it bills
-- expect: zero_rows
SELECT b.billing_id, b.invoice_date, a.scheduled_at
FROM healthcare.billing b JOIN healthcare.appointments a USING (appointment_id)
WHERE b.invoice_date < a.scheduled_at::date;

-- name: billing_duplicate_invoice_numbers
-- description: invoice numbers must be unique
-- expect: zero_rows
SELECT invoice_number, COUNT(*) AS n FROM healthcare.billing GROUP BY 1 HAVING COUNT(*) > 1;

-- name: billing_on_cancelled_appointments
-- description: invoices attached to CANCELLED appointments (business review item)
-- expect: info
SELECT COUNT(*) AS invoices_on_cancelled_appointments
FROM healthcare.billing b JOIN healthcare.appointments a USING (appointment_id)
WHERE a.status = 'CANCELLED';

-- name: completeness_profile_patients
-- description: how complete are optional patient attributes after cleaning?
-- expect: info
SELECT COUNT(*) AS patients,
       ROUND(100.0 * COUNT(phone) / COUNT(*), 1)        AS pct_phone,
       ROUND(100.0 * COUNT(email) / COUNT(*), 1)        AS pct_email,
       ROUND(100.0 * COUNT(address_line) / COUNT(*), 1) AS pct_address,
       ROUND(100.0 * COUNT(*) FILTER (WHERE gender <> 'U') / COUNT(*), 1)           AS pct_gender_known,
       ROUND(100.0 * COUNT(*) FILTER (WHERE blood_type <> 'UNKNOWN') / COUNT(*), 1) AS pct_blood_type_known
FROM healthcare.patients;

-- name: billing_revenue_by_status
-- description: sanity view of loaded revenue by payment status
-- expect: info
SELECT status, COUNT(*) AS invoices, SUM(total_amount) AS total_billed,
       SUM(insurance_paid) AS insurance_paid, SUM(patient_responsibility) AS patient_share
FROM healthcare.billing GROUP BY status ORDER BY total_billed DESC;
