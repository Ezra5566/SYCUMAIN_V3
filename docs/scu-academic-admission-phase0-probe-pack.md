# SCU — Academic Admission Phase 0: Constraint Probes and Migration Review Pack

**Status:** planning artefact. No migration exists yet, and nothing in this document has been run.
**Applies to:** Phase 0 of `docs/scu-academic-admission-implementation-plan.md`.
**Design contract:** `docs/scu-academic-admission-architecture.md` (Revision 3), §3.
**Audience:** the implementer writing the Phase 0 Alembic revision, and the reviewer signing it off.

---

## 1. Why this pack exists

Phase 0 is the only phase whose correctness cannot be demonstrated by the existing pytest suite.
`apps/api/tests/conftest.py` builds the schema with `Base.metadata.create_all`, which creates tables,
CHECK constraints and indexes declared on the models, but **does not create database triggers**. A
trigger-only rule — the `ADMITTED`-while-`ACTIVE` guard, immutability, no-delete, set-once pointer —
would therefore pass every test while being absent or wrong in a migrated database.

This pack closes that gap with two things:

1. A runnable SQL script of ~45 probes, executed against a **migrated scratch database**, that
   asserts each rule fails or succeeds with the expected SQLSTATE.
2. A migration review checklist that catches the failure modes the probes cannot see: wrong nullable
   columns, missing FKs, unsafe downgrades, model/migration drift, permission-seed mistakes.

Run the probes after every edit to the Phase 0 revision. If a probe fails, fix the migration. Do not
relax the probe unless the design itself is changed first. The same script is run by a path-filtered
CI job on migration changes; see `docs/scu-academic-admission-phase0-ci.md`.

---

## 2. Baseline and assumptions

- PostgreSQL 16 (`postgres:16-alpine` in `docker-compose.yml`).
- Alembic head at the time of writing is **`d1e2f3a4b5c6`** (`d1e2f3a4b5c6_document_scanning.py`).
  Re-verify with `cd apps/api && .venv/bin/python -m alembic heads`; the Phase 0 revision must set
  `down_revision` to whatever is current on the day it is written.
- Existing migrations declare `revision: str` / `down_revision: str | Sequence[str] | None`; follow
  that style.
- `Base` in `app/database/session.py` has **no metadata naming convention**. Constraint and index
  names must therefore be written explicitly, in both the migration and the model, or autogenerate
  will churn and PostgreSQL will invent names.
- `alembic/env.py` imports `from app.models import *`; new models must be exported from
  `app/models/__init__.py` or autogenerate will not see them.
- The probe fixtures are synthetic (`TEST-*`, `phase0-*@example.test`) and are removed by a final
  `ROLLBACK`.

**Column names in the probes follow design §3.1 exactly.** If the implementation renames a column,
the migration does not match the design and must be corrected before the probes are considered.

---

## 3. How to run

Use a **disposable scratch database** on the development PostgreSQL. Never run this against
`school_portal`, `school_portal_test`, production, or the isolated production-verification stack.

```bash
# 1. Create a scratch database (development container only)
docker compose -p sycumain exec -T postgres \
  createdb -U portal school_portal_phase0_probe

# 2. Apply the Phase 0 revision to the scratch database
cd apps/api
DATABASE_URL=postgresql://portal:portal@localhost:5433/school_portal_phase0_probe \
  .venv/bin/python -m alembic upgrade head

# 3. Extract the probe script from this document (writes outside the repo)
awk '/^-- BEGIN PHASE0 PROBES/{flag=1} flag{print} /^-- END PHASE0 PROBES/{flag=0}' \
  ../../docs/scu-academic-admission-phase0-probe-pack.md > /tmp/phase0_probes.sql

# 4. Run it; ON_ERROR_STOP makes any harness failure exit non-zero
psql "postgresql://portal:portal@localhost:5433/school_portal_phase0_probe" \
  -v ON_ERROR_STOP=1 -f /tmp/phase0_probes.sql
```

Expected result: a sequence of `NOTICE: PASS P-xx` lines, a final `NOTICE: Phase 0 probes complete`,
and `ROLLBACK` — exit code 0, no rows left behind.

Drop the scratch database afterwards:

```bash
docker compose -p sycumain exec -T postgres \
  dropdb -U portal school_portal_phase0_probe
```

The script runs inside `BEGIN … ROLLBACK`. If it aborts mid-way, the transaction is discarded when
the session ends; no fixture rows persist.

---

## 4. Probe catalogue

Expected SQLSTATEs: `23505` unique violation, `23514` check violation, `23503` foreign-key violation,
`23502` not-null violation, `P0001` `RAISE EXCEPTION` from a trigger.

| ID | Rule under test | Expected |
|---|---|---|
| P-01 | Second `ACTIVE` episode for one student | 23505 |
| P-02 | `ADMITTED` while another episode is `ACTIVE` | P0001 / 23514 / 23505 |
| P-03 | Two live episodes for the same `(student, intake)` | 23505 |
| P-04 | `PENDING` beside `ACTIVE` is allowed | success |
| P-05 | A second **terminal** episode in the same intake is allowed | success |
| P-06 | `ACTIVE` without `activated_at` | 23514 / P0001 |
| P-07 | `COMPLETED` without `ended_at` | 23514 |
| P-08 | `PENDING` with `ended_at` set | 23514 |
| P-09 | `WITHDRAWN` without `end_reason` | 23514 |
| P-10 | `MIGRATED` + `VERIFIED` with no confirmations | 23514 |
| P-11 | `REVOKED` with neither slot `REVOKED` | 23514 |
| P-12 | Slot `CONFIRMED` without a confirming timestamp | 23514 |
| P-13 | `NEW_ADMISSION` that is not `VERIFIED` | 23514 |
| P-14 | Admission offering from a different intake | 23503 |
| P-15 | Invalid transition `PENDING → COMPLETED` | P0001 / 23514 |
| P-16 | Two pending changes of one type on one admission | 23505 |
| P-17 | `APPROVED` change without reviewer | 23514 |
| P-18 | Self-approval (`reviewed_by = requested_by`) | 23514 |
| P-19 | `PROGRAM_CHANGE` without a target programme | 23514 |
| P-20 | `PROGRAM_CHANGE` to the same programme | 23514 |
| P-21 | A valid approved change is accepted | success |
| P-22 | Earlier-intake placement without authorizer/reason | 23514 |
| P-23 | Earlier-intake placement with a blank reason | 23514 |
| P-24 | Placement offering outside the placement intake | 23503 |
| P-25 | Second current placement for one student | 23505 |
| P-26 | Authorized earlier-intake placement is accepted | success |
| P-27 | Same-intake placement is accepted without a reason | success |
| P-28 | Inverted intake dates | 23514 / P0001 |
| P-29 | Status-history row with identical from/to | 23514 |
| P-30 | Date correction without a reason | 23502 |
| P-31 | Pointer-history row without a reason | 23502 |
| P-32 | Pointer change without the correction flag | P0001 |
| P-33 | Pointer cleared to `NULL` | P0001 |
| P-34 | Pointer change with the flag but no history row | P0001 |
| P-35 | Pointer change with flag and history row | success |
| P-36 | Changing `admission_intake_id` after verification | P0001 |
| P-37 | Changing `admitted_program_id` after verification | P0001 |
| P-38 | Changing `initial_status` after verification | P0001 |
| P-39 | Deleting an admission | P0001 |
| P-40 | Deleting a placement | P0001 |
| P-41 | Deleting a change request | P0001 |
| P-42 | Deleting a verification act | P0001 |
| P-43 | Deleting a programme referenced by an admission | 23503 |
| P-44 | Closing one placement and opening another is accepted | success |
| P-45 | A date correction with a reason is accepted | success |

Two rules are **not** probeable at Phase 0 and are covered later:

- Placement requires the episode to be `ADMITTED`/`ACTIVE` (a service rule, not a constraint) —
  Phase 3 tests.
- The period-date trigger's interaction with placement flags and academic records requires
  service-level ordering rules — Phase 5 tests. The probe pack only checks the date CHECK.

---

## 5. Probe script

```sql
-- BEGIN PHASE0 PROBES
\set ON_ERROR_STOP on
\timing off

BEGIN;

-- Fail loudly if the Phase 0 revision has not been applied here.
DO $guard$
BEGIN
    IF to_regclass('public.academic_admissions') IS NULL
       OR to_regclass('public.academic_placements') IS NULL
       OR to_regclass('public.academic_admission_changes') IS NULL
       OR to_regclass('public.academic_admission_verification_acts') IS NULL
       OR to_regclass('public.academic_admission_status_history') IS NULL
       OR to_regclass('public.academic_period_date_corrections') IS NULL
       OR to_regclass('public.student_original_admission_history') IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_name = 'students' AND column_name = 'original_admission_id'
       )
    THEN
        RAISE EXCEPTION 'Phase 0 schema is not applied to this database';
    END IF;
END
$guard$;

-- ---------------------------------------------------------------------------
-- Harness
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION pg_temp.expect_fail(
    p_label text, p_sql text, p_codes text[]
) RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    v_state text;
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS v_state = RETURNED_SQLSTATE;
        IF v_state = ANY (p_codes) THEN
            RAISE NOTICE 'PASS % (sqlstate %)', p_label, v_state;
            RETURN;
        END IF;
        RAISE EXCEPTION 'FAIL %: got sqlstate %, expected %', p_label, v_state, p_codes;
    END;
    RAISE EXCEPTION 'FAIL %: statement succeeded but must fail', p_label;
END
$fn$;

CREATE OR REPLACE FUNCTION pg_temp.expect_ok(
    p_label text, p_sql text
) RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    BEGIN
        EXECUTE p_sql;
        RAISE NOTICE 'PASS %', p_label;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'FAIL %: unexpected sqlstate % (%)', p_label, SQLSTATE, SQLERRM;
    END;
END
$fn$;

-- Deterministic synthetic UUIDs: 00000000-0000-4000-8000-<12 digits>
CREATE OR REPLACE FUNCTION pg_temp.tid(p_n bigint) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT ('00000000-0000-4000-8000-' || lpad(p_n::text, 12, '0'))::uuid
$fn$;

-- ---------------------------------------------------------------------------
-- Synthetic fixtures (no institutional data)
-- ---------------------------------------------------------------------------

INSERT INTO users (id, email, username, hashed_password, full_name,
                   is_active, is_superuser, must_change_password,
                   created_at, updated_at)
SELECT pg_temp.tid(1000 + n),
       'phase0-user-' || n || '@example.test',
       'phase0-user-' || n,
       'x',
       'Phase0 User ' || n,
       true, false, false, now(), now()
FROM generate_series(1, 20) AS n;

INSERT INTO students (id, user_id, student_id, first_name, last_name,
                      status, created_at, updated_at)
SELECT pg_temp.tid(2000 + n),
       pg_temp.tid(1000 + n),
       'TEST-ADM-' || lpad(n::text, 5, '0'),
       'Test', 'Student' || n,
       'ACTIVE', now(), now()
FROM generate_series(1, 20) AS n;

INSERT INTO majors (id, code, name, status, created_at, updated_at)
VALUES (pg_temp.tid(5500), 'TST-MAJ', 'Phase 0 Test Major', 'ACTIVE', now(), now());

INSERT INTO programs (id, major_id, code, name, duration_years, status, created_at, updated_at)
VALUES
    (pg_temp.tid(5001), pg_temp.tid(5500), 'TST-PRG',  'Phase 0 Test Programme',  4, 'ACTIVE', now(), now()),
    (pg_temp.tid(5002), pg_temp.tid(5500), 'TST-PRG2', 'Phase 0 Alternate Programme', 4, 'ACTIVE', now(), now());

INSERT INTO academic_periods (id, name, code, start_date, end_date, status, created_at, updated_at)
VALUES
    (pg_temp.tid(4001), 'Phase 0 Spring 2026', 'TST-2026S',  DATE '2026-02-01', DATE '2026-06-30', 'PLANNED', now(), now()),
    (pg_temp.tid(4002), 'Phase 0 Autumn 2025', 'TST-2025A',  DATE '2025-09-01', DATE '2025-12-20', 'COMPLETED', now(), now()),
    (pg_temp.tid(4003), 'Phase 0 Autumn 2026', 'TST-2026A',  DATE '2026-09-01', DATE '2026-12-20', 'PLANNED', now(), now());

INSERT INTO program_offerings (id, academic_period_id, program_id, source_id, source_key,
                               name, created_at, updated_at)
VALUES
    (pg_temp.tid(6001), pg_temp.tid(4001), pg_temp.tid(5001), 'TST-OFFER-S', 'test:offer:spring', 'Phase 0 Spring Offering', now(), now()),
    (pg_temp.tid(6002), pg_temp.tid(4002), pg_temp.tid(5001), 'TST-OFFER-A25', 'test:offer:autumn25', 'Phase 0 Autumn 2025 Offering', now(), now()),
    (pg_temp.tid(6003), pg_temp.tid(4003), pg_temp.tid(5002), 'TST-OFFER-A26', 'test:offer:autumn26', 'Phase 0 Autumn 2026 Offering', now(), now());

-- Admissions. Every row is synthetic and every rule below is exercised against these.
INSERT INTO academic_admissions (
    id, student_id, admission_intake_id, admitted_program_id,
    admitted_program_offering_id, current_program_id, status, initial_status,
    record_origin, verification_status,
    management_confirmation_state, admin_confirmation_state,
    verified_at, activated_at, ended_at, end_reason,
    created_by_id, created_at, updated_at
) VALUES
    -- S1: active + a prepared future admission (positive coexistence)
    (pg_temp.tid(3001), pg_temp.tid(2001), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3002), pg_temp.tid(2001), pg_temp.tid(4003), pg_temp.tid(5002), pg_temp.tid(6003), pg_temp.tid(5002),
     'PENDING', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), NULL, NULL, NULL, pg_temp.tid(1001), now(), now()),
    -- S2: second active target and a positive pending row
    (pg_temp.tid(3003), pg_temp.tid(2002), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    -- S3: completed, for terminal-duplicate and delete probes
    (pg_temp.tid(3004), pg_temp.tid(2003), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'COMPLETED', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), now() - INTERVAL '200 days', now() - INTERVAL '10 days', NULL,
     pg_temp.tid(1001), now(), now()),
    -- S4: migrated, unverified, for verification probes
    (pg_temp.tid(3005), pg_temp.tid(2004), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'PENDING', 'PENDING', 'MIGRATED', 'UNVERIFIED', 'NONE', 'NONE',
     NULL, NULL, NULL, NULL, pg_temp.tid(1002), now(), now()),
    -- S5: two terminal verified admissions, for pointer probes
    (pg_temp.tid(3006), pg_temp.tid(2005), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'COMPLETED', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), now() - INTERVAL '400 days', now() - INTERVAL '200 days', NULL,
     pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3007), pg_temp.tid(2005), pg_temp.tid(4002), pg_temp.tid(5001), pg_temp.tid(6002), pg_temp.tid(5001),
     'COMPLETED', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
     now(), now() - INTERVAL '600 days', now() - INTERVAL '400 days', NULL,
     pg_temp.tid(1001), now(), now()),
    -- S6..S17: active episodes used by placement, change and immutability probes
    (pg_temp.tid(3008), pg_temp.tid(2006), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3009), pg_temp.tid(2007), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3010), pg_temp.tid(2008), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3011), pg_temp.tid(2009), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3012), pg_temp.tid(2010), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3013), pg_temp.tid(2011), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3014), pg_temp.tid(2012), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3015), pg_temp.tid(2013), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3016), pg_temp.tid(2014), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3017), pg_temp.tid(2015), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3018), pg_temp.tid(2016), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(3019), pg_temp.tid(2017), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001), pg_temp.tid(5001),
     'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE', now(), now(), NULL, NULL, pg_temp.tid(1001), now(), now());

-- One current placement, one placement kept for the delete probe, one pending change,
-- one verification act, and the original-admission pointer for S5.
INSERT INTO academic_placements (
    id, student_id, admission_id, academic_period_id, program_offering_id,
    is_earlier_intake_placement, authorized_by_id, authorization_reason,
    effective_from, ended_at, created_by_id, created_at, updated_at
) VALUES
    (pg_temp.tid(7001), pg_temp.tid(2006), pg_temp.tid(3008), pg_temp.tid(4001), pg_temp.tid(6001),
     false, NULL, NULL, DATE '2026-02-01', NULL, pg_temp.tid(1001), now(), now()),
    (pg_temp.tid(7002), pg_temp.tid(2014), pg_temp.tid(3016), pg_temp.tid(4001), pg_temp.tid(6001),
     false, NULL, NULL, DATE '2026-02-01', NULL, pg_temp.tid(1001), now(), now());

INSERT INTO academic_admission_changes (
    id, admission_id, change_type, from_program_id, to_program_id,
    proposed_data, current_data_snapshot, reason,
    requested_by_id, requested_at, status
) VALUES (
    pg_temp.tid(8001), pg_temp.tid(3009), 'PROGRAM_CHANGE', pg_temp.tid(5001), pg_temp.tid(5002),
    '{}'::jsonb, '{}'::jsonb, 'Phase 0 probe fixture',
    pg_temp.tid(1002), now(), 'PENDING'
);

INSERT INTO academic_admission_verification_acts (
    id, admission_id, slot, action, actor_id, acted_at,
    candidate_intake_id, candidate_program_id, evidence_type,
    evidence_reference, evidence_note, resulting_verification_status
) VALUES (
    pg_temp.tid(9001), pg_temp.tid(3005), 'MANAGEMENT', 'CONFIRM', pg_temp.tid(1002), now(),
    pg_temp.tid(4001), pg_temp.tid(5001), 'REGISTER_EXTRACT',
    'TEST-REGISTER-0001', 'Synthetic fixture', 'UNVERIFIED'
);

UPDATE students
   SET original_admission_id = pg_temp.tid(3006), updated_at = now()
 WHERE id = pg_temp.tid(2005);

-- ---------------------------------------------------------------------------
-- P-01 .. P-05  one active, pending coexistence, per-intake uniqueness
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-01 second ACTIVE episode', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at, activated_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3201), pg_temp.tid(2002), pg_temp.tid(4002), pg_temp.tid(5001), pg_temp.tid(6002),
            pg_temp.tid(5001), 'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23505']);

SELECT pg_temp.expect_fail('P-02 ADMITTED while another episode is ACTIVE', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3202), pg_temp.tid(2001), pg_temp.tid(4002), pg_temp.tid(5001), pg_temp.tid(6002),
            pg_temp.tid(5001), 'ADMITTED', 'ADMITTED', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['P0001', '23514', '23505']);

SELECT pg_temp.expect_fail('P-03 duplicate live episode for one intake', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3203), pg_temp.tid(2001), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23505']);

SELECT pg_temp.expect_ok('P-04 PENDING beside ACTIVE', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3204), pg_temp.tid(2002), pg_temp.tid(4002), pg_temp.tid(5001), pg_temp.tid(6002),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$);

SELECT pg_temp.expect_ok('P-05 second terminal episode in one intake', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        activated_at, ended_at, end_reason, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3205), pg_temp.tid(2003), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'CANCELLED', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), NULL, now(), 'Synthetic cancellation', pg_temp.tid(1001), now(), now())
$q$);

-- ---------------------------------------------------------------------------
-- P-06 .. P-15  lifecycle and verification CHECKs, transition guard, FKs
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-06 ACTIVE without activated_at', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3206), pg_temp.tid(2018), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'ACTIVE', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514', 'P0001']);

SELECT pg_temp.expect_fail('P-07 COMPLETED without ended_at', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        activated_at, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3207), pg_temp.tid(2018), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'COMPLETED', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-08 PENDING with ended_at', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        ended_at, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3208), pg_temp.tid(2018), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-09 WITHDRAWN without reason', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        activated_at, ended_at, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3209), pg_temp.tid(2018), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'WITHDRAWN', 'ACTIVE', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), now(), now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-10 migrated VERIFIED without confirmations', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3210), pg_temp.tid(2019), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'MIGRATED', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-11 REVOKED without a revoked slot', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3211), pg_temp.tid(2019), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'MIGRATED', 'REVOKED', 'NONE', 'NONE',
            pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-12 CONFIRMED slot without timestamp', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3212), pg_temp.tid(2019), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'MIGRATED', 'UNVERIFIED', 'CONFIRMED', 'NONE',
            pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-13 NEW_ADMISSION not verified', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3213), pg_temp.tid(2020), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6001),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'NEW_ADMISSION', 'UNVERIFIED', 'NONE', 'NONE',
            pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-14 admission offering outside intake', $q$
    INSERT INTO academic_admissions (
        id, student_id, admission_intake_id, admitted_program_id, admitted_program_offering_id,
        current_program_id, status, initial_status, record_origin, verification_status,
        management_confirmation_state, admin_confirmation_state, verified_at,
        created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(3214), pg_temp.tid(2020), pg_temp.tid(4001), pg_temp.tid(5001), pg_temp.tid(6002),
            pg_temp.tid(5001), 'PENDING', 'PENDING', 'NEW_ADMISSION', 'VERIFIED', 'NONE', 'NONE',
            now(), pg_temp.tid(1001), now(), now())
$q$, ARRAY['23503']);

SELECT pg_temp.expect_fail('P-15 impossible transition PENDING to COMPLETED', $q$
    UPDATE academic_admissions
       SET status = 'COMPLETED', ended_at = now()
     WHERE id = pg_temp.tid(3002)
$q$, ARRAY['P0001', '23514']);

-- ---------------------------------------------------------------------------
-- P-16 .. P-21  change requests and single-approver rules
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-16 second pending change of one type', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status)
    VALUES (pg_temp.tid(8201), pg_temp.tid(3009), 'PROGRAM_CHANGE', pg_temp.tid(5001), pg_temp.tid(5002),
            '{}'::jsonb, '{}'::jsonb, 'Duplicate pending probe', pg_temp.tid(1002), now(), 'PENDING')
$q$, ARRAY['23505']);

SELECT pg_temp.expect_fail('P-17 APPROVED change without reviewer', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status)
    VALUES (pg_temp.tid(8202), pg_temp.tid(3010), 'PLACEMENT_CHANGE', pg_temp.tid(5001), pg_temp.tid(5001),
            '{}'::jsonb, '{}'::jsonb, 'Missing reviewer probe', pg_temp.tid(1002), now(), 'APPROVED')
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-18 self-approval', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status, reviewed_by_id, reviewed_at)
    VALUES (pg_temp.tid(8203), pg_temp.tid(3011), 'WITHDRAWAL', NULL, NULL,
            '{}'::jsonb, '{}'::jsonb, 'Self approval probe',
            pg_temp.tid(1002), now(), 'APPROVED', pg_temp.tid(1002), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-19 programme change without target', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status)
    VALUES (pg_temp.tid(8204), pg_temp.tid(3012), 'PROGRAM_CHANGE', pg_temp.tid(5001), NULL,
            '{}'::jsonb, '{}'::jsonb, 'Missing target probe', pg_temp.tid(1002), now(), 'PENDING')
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-20 programme change to the same programme', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status)
    VALUES (pg_temp.tid(8205), pg_temp.tid(3013), 'PROGRAM_CHANGE', pg_temp.tid(5001), pg_temp.tid(5001),
            '{}'::jsonb, '{}'::jsonb, 'Same programme probe', pg_temp.tid(1002), now(), 'PENDING')
$q$, ARRAY['23514']);

SELECT pg_temp.expect_ok('P-21 valid approved change', $q$
    INSERT INTO academic_admission_changes (
        id, admission_id, change_type, from_program_id, to_program_id,
        proposed_data, current_data_snapshot, reason,
        requested_by_id, requested_at, status, reviewed_by_id, reviewed_at, decision_reason)
    VALUES (pg_temp.tid(8206), pg_temp.tid(3014), 'PROGRAM_CHANGE', pg_temp.tid(5001), pg_temp.tid(5002),
            '{}'::jsonb, '{}'::jsonb, 'Valid approval probe',
            pg_temp.tid(1002), now(), 'APPROVED', pg_temp.tid(1001), now(), 'Synthetic approval')
$q$);

-- ---------------------------------------------------------------------------
-- P-22 .. P-27  placement authorization
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-22 earlier-intake placement without authorization', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7201), pg_temp.tid(2015), pg_temp.tid(3017), pg_temp.tid(4002), pg_temp.tid(6002),
            true, DATE '2025-09-01', pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-23 earlier-intake placement with blank reason', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, authorized_by_id, authorization_reason,
        effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7202), pg_temp.tid(2015), pg_temp.tid(3017), pg_temp.tid(4002), pg_temp.tid(6002),
            true, pg_temp.tid(1001), '   ', DATE '2025-09-01', pg_temp.tid(1001), now(), now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-24 placement offering outside intake', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7203), pg_temp.tid(2015), pg_temp.tid(3017), pg_temp.tid(4001), pg_temp.tid(6002),
            false, DATE '2026-02-01', pg_temp.tid(1001), now(), now())
$q$, ARRAY['23503']);

SELECT pg_temp.expect_fail('P-25 second current placement', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7204), pg_temp.tid(2006), pg_temp.tid(3008), pg_temp.tid(4001), pg_temp.tid(6001),
            false, DATE '2026-02-01', pg_temp.tid(1001), now(), now())
$q$, ARRAY['23505']);

SELECT pg_temp.expect_ok('P-26 authorized earlier-intake placement', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, authorized_by_id, authorization_reason,
        effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7205), pg_temp.tid(2015), pg_temp.tid(3017), pg_temp.tid(4002), pg_temp.tid(6002),
            true, pg_temp.tid(1001), 'Approved earlier-intake placement (synthetic)',
            DATE '2025-09-01', pg_temp.tid(1001), now(), now())
$q$);

SELECT pg_temp.expect_ok('P-27 same-intake placement without reason', $q$
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7206), pg_temp.tid(2016), pg_temp.tid(3018), pg_temp.tid(4001), pg_temp.tid(6001),
            false, DATE '2026-02-01', pg_temp.tid(1001), now(), now())
$q$);

-- ---------------------------------------------------------------------------
-- P-28 .. P-31  dates, status history, correction/history reasons
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-28 inverted intake dates', $q$
    UPDATE academic_periods
       SET end_date = start_date - 1, updated_at = now()
     WHERE id = pg_temp.tid(4002)
$q$, ARRAY['23514', 'P0001']);

SELECT pg_temp.expect_fail('P-29 status history with identical from/to', $q$
    INSERT INTO academic_admission_status_history (
        id, admission_id, from_status, to_status, actor_id, is_correction, created_at)
    VALUES (pg_temp.tid(9301), pg_temp.tid(3017), 'ACTIVE', 'ACTIVE', pg_temp.tid(1001), false, now())
$q$, ARRAY['23514']);

SELECT pg_temp.expect_fail('P-30 date correction without reason', $q$
    INSERT INTO academic_period_date_corrections (
        id, academic_period_id, previous_start_date, previous_end_date,
        new_start_date, new_end_date, reason, actor_id, created_at,
        placements_reflagged, admissions_rechecked)
    VALUES (pg_temp.tid(9401), pg_temp.tid(4002), DATE '2025-09-01', DATE '2025-12-20',
            DATE '2025-09-02', DATE '2025-12-19', NULL, pg_temp.tid(1001), now(), 0, 0)
$q$, ARRAY['23502']);

SELECT pg_temp.expect_fail('P-31 pointer history without reason', $q$
    INSERT INTO student_original_admission_history (
        id, student_id, previous_admission_id, new_admission_id, reason, actor_id, created_at)
    VALUES (pg_temp.tid(9501), pg_temp.tid(2005), pg_temp.tid(3006), pg_temp.tid(3007),
            NULL, pg_temp.tid(1001), now())
$q$, ARRAY['23502']);

-- ---------------------------------------------------------------------------
-- P-32 .. P-35  original-admission pointer is set once, corrected only explicitly
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-32 pointer change without correction flag', $q$
    UPDATE students
       SET original_admission_id = pg_temp.tid(3007), updated_at = now()
     WHERE id = pg_temp.tid(2005)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-33 pointer cleared', $q$
    UPDATE students
       SET original_admission_id = NULL, updated_at = now()
     WHERE id = pg_temp.tid(2005)
$q$, ARRAY['P0001']);

SELECT set_config('scu.original_admission_correction', 'on', true);

SELECT pg_temp.expect_fail('P-34 pointer change with flag but no history', $q$
    UPDATE students
       SET original_admission_id = pg_temp.tid(3007), updated_at = now()
     WHERE id = pg_temp.tid(2005)
$q$, ARRAY['P0001']);

SELECT set_config('scu.original_admission_correction', 'off', true);

SELECT pg_temp.expect_ok('P-35 pointer change with flag and history', $q$
    INSERT INTO student_original_admission_history (
        id, student_id, previous_admission_id, new_admission_id, reason, actor_id, created_at)
    VALUES (pg_temp.tid(9502), pg_temp.tid(2005), pg_temp.tid(3006), pg_temp.tid(3007),
            'Synthetic correction', pg_temp.tid(1001), now());
    SELECT set_config('scu.original_admission_correction', 'on', true);
    UPDATE students
       SET original_admission_id = pg_temp.tid(3007), updated_at = now()
     WHERE id = pg_temp.tid(2005)
$q$);

SELECT set_config('scu.original_admission_correction', 'off', true);

-- ---------------------------------------------------------------------------
-- P-36 .. P-43  immutability, no-delete, referential protection
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_fail('P-36 intake unchanged after verification', $q$
    UPDATE academic_admissions
       SET admission_intake_id = pg_temp.tid(4002)
     WHERE id = pg_temp.tid(3017)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-37 admitted programme unchanged after verification', $q$
    UPDATE academic_admissions
       SET admitted_program_id = pg_temp.tid(5002)
     WHERE id = pg_temp.tid(3017)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-38 initial_status unchanged after verification', $q$
    UPDATE academic_admissions
       SET initial_status = 'ADMITTED'
     WHERE id = pg_temp.tid(3017)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-39 admission delete refused', $q$
    DELETE FROM academic_admissions WHERE id = pg_temp.tid(3004)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-40 placement delete refused', $q$
    DELETE FROM academic_placements WHERE id = pg_temp.tid(7002)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-41 change delete refused', $q$
    DELETE FROM academic_admission_changes WHERE id = pg_temp.tid(8001)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-42 verification act delete refused', $q$
    DELETE FROM academic_admission_verification_acts WHERE id = pg_temp.tid(9001)
$q$, ARRAY['P0001']);

SELECT pg_temp.expect_fail('P-43 programme delete blocked by admission FK', $q$
    DELETE FROM programs WHERE id = pg_temp.tid(5001)
$q$, ARRAY['23503']);

-- ---------------------------------------------------------------------------
-- P-44 .. P-45  placement supersession and a valid correction
-- ---------------------------------------------------------------------------

SELECT pg_temp.expect_ok('P-44 close placement then open another', $q$
    UPDATE academic_placements
       SET ended_at = now(), updated_at = now()
     WHERE id = pg_temp.tid(7001);
    INSERT INTO academic_placements (
        id, student_id, admission_id, academic_period_id, program_offering_id,
        is_earlier_intake_placement, effective_from, created_by_id, created_at, updated_at)
    VALUES (pg_temp.tid(7207), pg_temp.tid(2006), pg_temp.tid(3008), pg_temp.tid(4001), pg_temp.tid(6001),
            false, DATE '2026-02-01', pg_temp.tid(1001), now(), now())
$q$);

SELECT pg_temp.expect_ok('P-45 date correction with reason', $q$
    INSERT INTO academic_period_date_corrections (
        id, academic_period_id, previous_start_date, previous_end_date,
        new_start_date, new_end_date, reason, actor_id, created_at,
        placements_reflagged, admissions_rechecked)
    VALUES (pg_temp.tid(9402), pg_temp.tid(4002), DATE '2025-09-01', DATE '2025-12-20',
            DATE '2025-09-02', DATE '2025-12-19', 'Synthetic correction probe',
            pg_temp.tid(1001), now(), 0, 0)
$q$);

DO $done$
BEGIN
    RAISE NOTICE 'Phase 0 probes complete';
END
$done$;

ROLLBACK;
-- END PHASE0 PROBES
```

### 5.1 Reading the result

- `PASS P-xx` — the rule behaved as designed.
- `FAIL P-xx: statement succeeded but must fail` — the constraint or trigger is missing or too weak.
- `FAIL P-xx: got sqlstate …` — wrong object is firing: for example a `23503` where a `23514` was
  expected usually means a NOT NULL column is absent rather than the intended CHECK; a `23505` where
  a `P0001` was expected usually means the rule was implemented as a unique index and cannot express
  the `ADMITTED`–`ACTIVE` case.
- `FAIL P-xx: unexpected sqlstate …` on a positive probe — a fixture or constraint is wrong; do not
  "fix" it by widening the constraint without checking the design.

### 5.2 Known limitation of P-35

The pointer-correction trigger contract checks two things: the transaction-local flag
`scu.original_admission_correction = 'on'`, and a history row inserted in the same transaction. P-35
inserts the history row, enables the flag with `set_config(…, true)` and updates the pointer inside
one dynamic statement, then the script disables the flag. If the implementation chooses a different
contract (for example a function-level flag), the probe must be updated **and** the design's trigger
contract amended first. Silent divergence here is how a wrong original intake later reaches an
immigration cohort.

---

## 6. Migration review checklist

Review against the diff, not the summary in the PR description. Tick each line or record why it does
not apply.

### 6.1 Revision mechanics

- [ ] Exactly one new revision; `down_revision` equals `alembic heads` on the day of writing
      (`d1e2f3a4b5c6` at the time of this pack — re-verify).
- [ ] Revision identifier follows the existing 12-hex-character style; file name is
      `<revision>_<description>.py`.
- [ ] `upgrade()` and `downgrade()` are both present; neither is `pass`.
- [ ] `alembic upgrade head --sql` (offline) produces the expected DDL and no DML beyond reference
      seeding.
- [ ] Running `alembic upgrade head` twice is a no-op.
- [ ] `alembic downgrade -1` succeeds on a database where the new tables are empty, and `upgrade head`
      after it succeeds again.

### 6.2 Tables and columns

- [ ] All seven new tables exist: `academic_admissions`, `academic_admission_status_history`,
      `academic_placements`, `academic_admission_changes`,
      `academic_admission_verification_acts`, `academic_period_date_corrections`,
      `student_original_admission_history`.
- [ ] `students.original_admission_id` is added **nullable**, with no server default, no backfill and
      no data statement.
- [ ] `program_offerings` gains `UNIQUE (academic_period_id, id)`; no other column change.
- [ ] UUID columns use `postgresql.UUID(as_uuid=True)`; timestamps use
      `sa.DateTime(timezone=True)`; dates use `sa.Date()`.
- [ ] Status/state columns are `String(20)`/`String(40)` with explicit values, matching the design's
      spellings and casing (upper snake case).
- [ ] Every `NOT NULL` column either has a value in the design's write path or a deliberate
      `server_default`; nothing is required that the API cannot supply.
- [ ] No column is added to an existing academic/timetable table other than the two changes above.
- [ ] No `DROP`, `ALTER … TYPE`, or data `UPDATE`/`DELETE` appears anywhere in `upgrade()`.

### 6.3 Keys, relationships and delete behaviour

- [ ] `student_id` → `students.id`, `academic_period_id` → `academic_periods.id`, offering and
      programme references → their tables, all `ON DELETE RESTRICT` (explicit, not left to default).
- [ ] Actor columns (`created_by_id`, `confirmed_*_by_id`, `authorized_by_id`, `reviewed_by_id`,
      `requested_by_id`) reference `users.id` with `RESTRICT`.
- [ ] `academic_placements.admission_id` → `academic_admissions.id`; no placement without an episode.
- [ ] Composite FKs exist for **both** admission and placement:
      `(admission_intake_id, admitted_program_offering_id)` and
      `(academic_period_id, program_offering_id)` referencing
      `program_offerings (academic_period_id, id)`.
- [ ] `students.original_admission_id` references `academic_admissions.id` and is unique where not
      null.
- [ ] `academic_admission_changes.admission_id` and
      `academic_admission_status_history.admission_id` are indexed.
- [ ] `parent`/child relationships are not accidentally configured with `cascade="all, delete"` in
      the ORM models.

### 6.4 Indexes and uniqueness

- [ ] Partial unique index on `(student_id) WHERE status = 'ACTIVE'` exists with exactly that
      predicate.
- [ ] Partial unique index on `(student_id, admission_intake_id) WHERE status IN
      ('PENDING','ADMITTED','ACTIVE')` exists; terminal duplicates are permitted.
- [ ] Partial unique index on `(student_id) WHERE ended_at IS NULL` for the current placement.
- [ ] Partial unique index on `(admission_id, change_type) WHERE status = 'PENDING'`.
- [ ] Unique index on `students.original_admission_id WHERE … IS NOT NULL`.
- [ ] Query indexes: `(admission_intake_id, status)` on admissions; `(student_id)` on placements,
      changes, acts and history.
- [ ] Predicates are `IMMUTABLE` expressions (no `now()`, no stable functions).
- [ ] Index names are explicit and match the model declarations.

### 6.5 CHECK constraints

- [ ] `ACTIVE` ⇒ `activated_at IS NOT NULL`.
- [ ] `(status IN ('COMPLETED','WITHDRAWN','CANCELLED')) = (ended_at IS NOT NULL)` — equivalence, not
      implication, so `PENDING` cannot carry an end date.
- [ ] `WITHDRAWN`/`CANCELLED` ⇒ non-null `end_reason`; placement reason is non-blank via `btrim`.
- [ ] Verification-state checks are consistent with retained confirmations:
      `VERIFIED` ⇒ both slots `CONFIRMED`; `NEW_ADMISSION` is exempt and must be `VERIFIED`;
      `REVOKED` ⇒ at least one slot `REVOKED`; slot `REVOKED` ⇔ revoked timestamp present;
      slot `CONFIRMED` ⇒ confirmed timestamp present.
- [ ] `academic_periods` has `CHECK (end_date >= start_date)`.
- [ ] Change checks: `PROGRAM_CHANGE` has a target and target ≠ source; `APPROVED`/`REJECTED` ⇒
      reviewer and timestamp; reviewer ≠ requester.
- [ ] Status-history check rejects `from_status = to_status` where `from_status` is not null.
- [ ] CHECK expressions are NULL-safe for nullable columns (a CHECK that evaluates to NULL passes).

### 6.6 Triggers

- [ ] Seven triggers exist with the design's responsibilities: admitted/active guard, transition
      guard + history writer, admission immutability, no-delete, original-pointer set-once, period
      date recheck, change review guard.
- [ ] All are `BEFORE INSERT OR UPDATE` (or `BEFORE DELETE` for the no-delete trigger), `FOR EACH
      ROW`, and return `NEW`/`OLD` correctly.
- [ ] No trigger is `SECURITY DEFINER`; if any dynamic SQL is used, `search_path` is pinned.
- [ ] Function names are prefixed (`scu_…`) and created in the same revision; `downgrade()` drops
      them after dropping their triggers.
- [ ] The `ADMITTED`-while-`ACTIVE` rule is a trigger, not a single index; the design cannot be
      expressed by a unique index alone.
- [ ] The status-history writer does not fire recursively and does not require a history row for the
      history insert itself.
- [ ] The pointer trigger reads the correction flag with `current_setting('scu.original_admission_correction', true)`
      (missing-ok) and requires a history row in the same transaction.
- [ ] The immutability trigger protects `admission_intake_id`, `admitted_program_id`,
      `admitted_program_offering_id` and `initial_status`, and does not block `current_program_id`
      updates or legitimate status/end changes.
- [ ] Updates made by the API's own correction paths (status correction, pointer correction) still
      pass the triggers rather than being special-cased by disabling them.

### 6.7 Permissions

- [ ] The twelve codenames from design §8 exist exactly once each in `app/permissions/constants.py`.
- [ ] ADMIN receives all; MANAGEMENT receives the operational set; TEACHER and STUDENT receive none
      of the admission/cohort permissions.
- [ ] Slot-specific permissions are not granted to the wrong role.
- [ ] `seed_roles_and_permissions` remains idempotent: running it twice does not duplicate
      `permissions` or `role_permissions` rows, and does not remove existing grants.
- [ ] No permission is granted only in the migration; the seed is the single source.

### 6.8 Model and migration parity

- [ ] New models are exported from `app/models/__init__.py`; `alembic/env.py` imports them.
- [ ] Every CHECK, partial unique index and FK in the migration is also declared on the model with
      the same name (so `create_all` in tests produces the same constraints).
- [ ] Autogenerate against a migrated database reports no pending operations (or the only diff is a
      documented, intentional server default).
- [ ] Triggers are documented as migration-only; a comment or test note says `create_all` does not
      create them.
- [ ] `Base.metadata.create_all` on an empty database still succeeds (no dependency on migration
      ordering).

### 6.9 Data safety

- [ ] The revision contains no `INSERT`, `UPDATE` or `DELETE` against academic, student or
      immigration data.
- [ ] Permission seeding is the only reference-data write, and it is reference configuration, not
      institutional data.
- [ ] Existing row counts for majors, programmes, periods, offerings, courses, classrooms, sections,
      timetable entries, enrolments, attendance, assessments, grades and history are identical
      before and after the migration.
- [ ] No default, trigger or backfill populates `students.original_admission_id`.
- [ ] No existing constraint is dropped or relaxed to make the new schema fit.

### 6.10 Test and evidence

- [ ] `make test-api` passes; no existing test expectation was weakened.
- [ ] `make lint-api` passes.
- [ ] The probe script in §5 passes on a freshly migrated scratch database.
- [ ] The probe script passes again after `downgrade -1` + `upgrade head` on that scratch database.
- [ ] A migrated copy of development data was tested (structure only): migration applies, counts
      unchanged, no orphan rows.
- [ ] Evidence is attached to the review: `alembic heads` output, probe output, count comparison.

### 6.11 Rollback readiness

- [ ] `downgrade()` refuses to drop objects when any new table contains rows (raise a clear error)
      rather than silently discarding data.
- [ ] The documented rollback for this phase is "revert the release, leave the additive schema", not
      "downgrade a database with data".
- [ ] No phase-0 object is required by an existing feature, so reverting the release cannot break
      current behaviour.

---

## 7. Sign-off

| Item | Result | Evidence / note |
|---|---|---|
| Revision id and head | | |
| Probe run (scratch) | | |
| Probe run after downgrade/upgrade | | |
| Existing suite | | |
| Lint | | |
| Row-count comparison | | |
| Permission seed idempotency | | |
| Reviewer | | |
| Date | | |

---

## 8. What this pack does not cover

- Service-level rules (placement requires `ADMITTED`/`ACTIVE`, authentication, role checks).
- The period-date trigger's recomputation of placement flags — Phase 5.
- API, UI, locale or migration-workflow acceptance — Phases 1–8.
- Any execution against development, production or the isolated production-verification environment.

No migration, database, data or environment was modified to produce this pack.
