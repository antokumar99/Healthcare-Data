# Healthcare Data Migration & Validation Pipeline

An end-to-end ETL project that migrates a deliberately messy **legacy MySQL** healthcare database
(patients, appointments, billing) into a strict, constraint-enforced **PostgreSQL** schema, and then
*proves* the migration is correct with SQL reconciliation, integrity and error-detection suites.

```
 Python (Faker)          MySQL (legacy)            Python / pandas              PostgreSQL (target)
┌──────────────┐  load  ┌──────────────┐ extract ┌────────────────────┐ batch  ┌────────────────────┐
│ generate_data│ ─────► │ patients     │ ──────► │ cleaning.py        │ insert │ patients           │
│ dirty CSVs   │        │ appointments │ chunked │  • missing values  │ ─────► │ appointments       │
└──────────────┘        │ billing      │ stream  │  • de-duplication  │        │ billing            │
                        │ (no FKs,     │         │  • standardisation │        │ migration_errors ◄─┼─ quarantine
                        │  loose types)│         │  • FK re-pointing  │        │ migration_audit  ◄─┼─ control totals
                        └──────────────┘         └────────────────────┘        └─────────┬──────────┘
                               │                                                         │
                               └────────────────── sql/validation/*.sql ─────────────────┘
                                      reconciliation · integrity · error detection
```

## Quick start

```bash
pip install -r requirements.txt
docker compose up -d                 # MySQL 8 (source) + PostgreSQL 16 (target)
cp .env.example .env                 # defaults already match docker-compose.yml
python run_pipeline.py all           # generate -> load MySQL -> migrate -> validate
python run_pipeline.py selftest      # inject 10 corruptions; prove validators catch every one
pytest -q                            # 28 tests (integration tests auto-skip without DBs)
```

No Docker? Point `.env` at any MySQL/MariaDB and PostgreSQL ≥ 13 you have; the pipeline creates the
databases/schemas itself.

| Command | What it does |
|---|---|
| `python run_pipeline.py generate --patients 2000` | Synthetic dirty CSVs → `data/raw/` |
| `python run_pipeline.py load-source` | Loads the CSVs into the legacy MySQL schema |
| `python run_pipeline.py migrate --batch-size 1000` | Extract → clean → create PG schema → batch load → audit |
| `python run_pipeline.py validate` | Runs all SQL suites + cross-database checks → `reports/validation_report.md` |
| `python run_pipeline.py selftest` | Fault-injection test of the validators |
| `python run_pipeline.py all` | generate → load-source → migrate → validate |

`validate` and `selftest` exit non-zero on failure, so they drop straight into CI.

## Project layout

```
run_pipeline.py                  CLI entrypoint
healthcare_pipeline/
  config.py  db.py               settings (.env), connection helpers
  generate_data.py               synthetic data + controlled "dirt" injection
  load_source.py                 CSV -> MySQL legacy tables
  schema_mapping.py              MySQL->PG column/type mapping (single source of truth)
  extract.py                     chunked/streamed extraction from MySQL
  cleaning.py                    missing values, de-dup, standardisation, FK re-pointing
  migrate.py                     schema creation, batch inserts, quarantine, audit
  validate.py                    SQL-suite runner + cross-database checks + report
  selftest.py                    fault injection
sql/
  mysql_schema.sql               legacy source schema
  postgres_schema.sql            target schema (+ migration_errors, migration_audit)
  validation/01..05_*.sql        51 named queries (reconciliation, integrity, errors, source profile)
tests/                           unit (no DB) + integration (isolated *_test databases)
docs/schema_mapping.md           generated column/type mapping table
reports/                         sample outputs from a real run (see below)
data/raw, data/staging           sample generated CSVs / staged raw & clean extracts
```

## 1. Synthetic data (Python + Faker, seeded & reproducible)

The generator creates *realistic* data first and then injects specific, countable defects:

| Defect | Where | Example |
|---|---|---|
| Mixed date formats | `patients.dob` (free-text in legacy) | `1984-03-02`, `03/02/1984`, `02-Mar-1984`, `1984/03/02` |
| Mixed phone formats / invalid | `patients.phone` | `(555) 123-4567`, `5551234567`, `+1 555 123 4567`, `5551234` |
| Inconsistent categoricals | gender, appointment & payment status | `M/male/MALE`, `Done/attended/COMPLETED`, `cxl/canceled` |
| Missing values | optional *and* required fields | null phone/email/blood type; a few null MRN / DOB / name |
| Lost leading zeros, bad emails, odd casing | zip, email, names, MRN, provider | `4921`, `jane.doe` (no @), `  mrn100004 ` |
| **Duplicate patients** | same MRN, new surrogate id (5%) | children (appointments) split across both copies |
| Duplicate appointments / invoices | same slot / same invoice number | |
| **Orphans** | appointments → missing patient; invoices → missing appointment | legacy schema has no FKs |
| Money errors | billing | split ≠ total, missing insurer share, negative totals |

## 2. Cleaning rules (`cleaning.py`)

* **Nothing disappears silently** – every source row ends as exactly one of *loaded*, *merged duplicate*, or *rejected*.
* **Fix what is safely fixable; reject what isn't.** Optional attributes are standardised or defaulted; missing
  *required* keys (MRN, DOB, invoice number, amounts) or broken references are rejected, never invented.
* **Missing values:** `N/A`/`null`/`unknown` placeholders → real NULLs; gender → `U`, blood type → `UNKNOWN`,
  provider → `Unassigned`, department → `General Medicine`, payer → `Self-Pay`, duration → 30 min;
  missing `insurance_paid` is inferred as `total − patient_share`; missing invoice date → appointment date.
* **De-duplication with survivorship:** patients are keyed on normalised MRN; the *most complete* record survives
  and empty fields are back-filled from its duplicates. Appointments dedupe on (patient, time, provider), invoices on
  invoice number.
* **Referential integrity is preserved through merges:** a map `duplicate_id → surviving_id` re-points appointments
  and invoices, so merging two patient records doesn't orphan their history.
* **Standardisation:** 4 date formats → `DATE`; phones → `NNN-NNN-NNNN`; zip left-padded; emails lower-cased/validated;
  state upper-cased; names title-cased only when ALL-CAPS/lower (keeps `McDonald`); `Dr.` prefix normalised;
  statuses mapped to controlled vocabularies.
* **Money:** `total = insurance_paid + patient_responsibility` is enforced; inconsistent splits are recomputed (and counted).

The full per-field change log of a run is in `reports/cleaning_report.md`.

## 3. MySQL → PostgreSQL migration (`migrate.py`)

**Schema mapping** (`schema_mapping.py` → `docs/schema_mapping.md`), e.g. `INT AUTO_INCREMENT → INTEGER IDENTITY`,
`TINYINT(1) → BOOLEAN`, `VARCHAR dob → DATE`, `free-text status → VARCHAR + CHECK`, `DATETIME → TIMESTAMP`; renames such as
`dob → date_of_birth`, `doctor_name → provider_name`, `payment_status → status`. The target adds `NOT NULL`, `CHECK`, `UNIQUE`
and real foreign keys that the legacy schema never had. Source ids are preserved and the identity sequences are reset
afterwards so future inserts don't collide.

**Batch inserts:** parents before children (patients → appointments → billing), `psycopg2.extras.execute_values`
in configurable batches, one commit per batch.

**Failure isolation:** each batch runs inside a `SAVEPOINT`. If it fails, we roll back to the savepoint and retry
*row by row*, so one bad row never costs the other 999. Each failing row is written to `healthcare.migration_errors`
(`LOAD_FAILURE`) with its payload.

**Quarantine & audit:** rejected rows and merged duplicates are stored in `migration_errors` with the **full raw
source record as JSONB** (so they can be investigated and replayed). `migration_audit` stores per-table control
totals captured *before* loading: row counts, an md5 checksum of the primary keys, and the billing amount total.

## 4. SQL validation (`sql/validation/`)

Each file holds named queries tagged `-- expect: zero_rows` (query returns *violations*; any row = FAIL) or `info`.

| File | Purpose | Highlights |
|---|---|---|
| `01_reconciliation.sql` | **Record reconciliation** | `source = loaded + merged + rejected + failed`; target `COUNT(*)` vs audit; md5 of primary keys; billing control total; no id both loaded and quarantined |
| `02_referential_integrity.sql` | **Integrity (relationships)** | orphan appointments/invoices; invoice patient ≠ appointment patient; merged ids still present; every merge survivor exists |
| `03_data_integrity.sql` | **Integrity (values)** | DOB range, MRN/phone/email/state/zip formats, duplicate slots, billing math, invoice dates, completed-in-future, potential duplicate patients |
| `04_migration_errors.sql` | **Migration error detection** | `LOAD_FAILURE`s, missing audit rows, out-of-sync sequences, untraceable quarantine rows; reject reasons, cascade rejections, money held in quarantine |
| `05_source_mysql_profile.sql` | **Source profiling (MySQL)** | duplicate MRNs, orphans, null profile, spelling/format inventories |

`validate.py` adds **cross-database checks** that no single SQL statement can do: MySQL row counts = audit, and
**money conservation** – `MySQL SUM(total) = PostgreSQL SUM(total) + amount held in quarantine`. Also: no MRN invented in
the target, and no MRN silently lost.

### Proof the validators work (`selftest`)
Passing checks mean little unless the checks can fail. `selftest` re-migrates, corrupts PostgreSQL in one specific way,
and asserts the right checks fire: deleted invoice, +$10 on an invoice that still balances, orphan row inserted with FKs
bypassed, corrupted phone, un-normalised MRN, injected load failure, rewound sequence, future "completed" visit, and
rows deleted from quarantine. **All 10 are detected** – see `reports/selftest_output.txt`.

## 5. Results from the included run (2,000 base patients)

| table | source | loaded | duplicates merged | rejected | load failures |
|---|---:|---:|---:|---:|---:|
| patients | 2,100 | 1,965 | 99 | 36 | 0 |
| appointments | 6,243 | 5,878 | 177 | 188 | 0 |
| billing | 4,512 | 4,275 | 85 | 152 | 0 |

37/37 validation checks pass; 10/10 injected faults detected; 28/28 tests pass. Migrating **~126k rows (20,000
patients) took ~11 s** end-to-end on a laptop-class sandbox. Of the 188 rejected appointments, 127 are *cascade* rejections
(their patient was rejected for a missing DOB/MRN/name) – fixing those patients upstream would recover them
(`cascade_rejections` query).

Where to look: `reports/validation_report.md`, `reports/cleaning_report.md`, `reports/quarantine_*.csv`, `reports/sample_run.log`.

## Design decisions & limits

* **Full-refresh target:** `migrate` drops and recreates the `healthcare` schema each run (idempotent, simple to reason
  about). An incremental/CDC mode would be a natural next step.
* **MRN is the identity key.** Deterministic and auditable. Probabilistic matching (same name + DOB, different MRN) is
  deliberately *not* auto-merged – the `potential_duplicate_patients` query surfaces candidates for human review.
* **Rejecting vs. imputing:** clinical/financial facts (DOB, amounts, invoice number) are never guessed.
* **Memory:** extraction streams in chunks, but cleaning loads each table into pandas. For hundreds of millions of rows,
  partition by id range and run the same stages per partition.
* **PHI:** all data is synthetic. For real data you'd add encryption in transit/at rest, access controls and
  masking of `raw_record` payloads in the quarantine table.
* Developed and verified against **MariaDB 10.11 + PostgreSQL 16**; SQL uses only syntax common to MySQL 8
  (`docker-compose.yml` pins MySQL 8.0 / PostgreSQL 16).
