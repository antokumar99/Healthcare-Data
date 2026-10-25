-- ============================================================================
-- SOURCE (legacy) schema - MySQL 8
-- Intentionally "legacy-style": loose types, no FKs, no natural-key constraints.
-- That is what makes the data dirty enough to need a real cleaning stage.
-- ============================================================================
DROP TABLE IF EXISTS billing;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS patients;

CREATE TABLE patients (
    patient_id   INT AUTO_INCREMENT PRIMARY KEY,
    mrn          VARCHAR(20),            -- medical record number (not unique in legacy!)
    first_name   VARCHAR(50),
    last_name    VARCHAR(50),
    dob          VARCHAR(20),            -- free-text date, mixed formats
    gender       VARCHAR(20),            -- M / male / Female / ...
    phone        VARCHAR(30),            -- mixed formats
    email        VARCHAR(100),
    address      VARCHAR(200),
    city         VARCHAR(60),
    state        VARCHAR(30),
    zip_code     VARCHAR(10),
    blood_type   VARCHAR(10),
    is_active    TINYINT(1) DEFAULT 1,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_patients_mrn (mrn)
) ENGINE=InnoDB;

CREATE TABLE appointments (
    appointment_id       INT AUTO_INCREMENT PRIMARY KEY,
    patient_id           INT,
    doctor_name          VARCHAR(80),
    department           VARCHAR(60),
    appointment_datetime DATETIME,
    status               VARCHAR(20),
    reason               TEXT,
    duration_minutes     SMALLINT,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_appt_patient (patient_id)
) ENGINE=InnoDB;

CREATE TABLE billing (
    billing_id             INT AUTO_INCREMENT PRIMARY KEY,
    appointment_id         INT,
    patient_id             INT,
    invoice_number         VARCHAR(30),
    service_code           VARCHAR(10),
    total_amount           DECIMAL(10,2),
    insurance_paid         DECIMAL(10,2),
    patient_responsibility DECIMAL(10,2),
    insurance_provider     VARCHAR(80),
    payment_status         VARCHAR(20),
    billing_date           DATE,
    KEY idx_bill_appt (appointment_id),
    KEY idx_bill_patient (patient_id)
) ENGINE=InnoDB;
