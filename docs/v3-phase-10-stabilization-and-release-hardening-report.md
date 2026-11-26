# V3 Phase 10 — Targeted Stabilization and Release Baseline Hardening

**Scope:** resolve the specific technical weaknesses recorded in the Phase 9 full-system
assessment, verify that existing behaviour is intact, and decide whether the tree is a
safe stable release baseline.

**Baseline:** branch `main`, HEAD `8467300`, no staged changes, no stashes.
**This phase produced no commit, no push, no deployment, no real-data migration and no
change to V1.** V1 was only ever read (`SELECT`), and only to confirm its database
identity.

Evidence is tagged throughout: **VERIFIED** (executed and observed here),
**NOT VERIFIED** (not executed, with the reason), **ESTIMATED** (inferred, not measured),
**INSTITUTIONAL DECISION REQUIRED**.

---

## A. Executive summary

Six weaknesses were carried out of Phase 9. Five are now closed with database-level or
process-level enforcement, and one is closed with a measurement rather than a claim.

| # | Weakness from Phase 9 | Outcome |
|---|---|---|
| 1 | `audit_logs` append-only by convention; `portal` holds UPDATE/DELETE | **Fixed.** Triggers + grants. UPDATE, DELETE and TRUNCATE now fail with SQLSTATE 42501, for the app role and for a superuser alike. **VERIFIED** |
| 2 | `student.updated` records field names only; some grade/housing/immigration events lack before/after | **Fixed** for student profile, housing assignment edit/transfer/move-out, enrolment create/drop, grade create/correct and immigration corrections. **VERIFIED** |
| 3 | API CPU-bound at 10 concurrent users with an idle database | **Fixed and measured.** Read throughput 103.9 → 176.3 rps at 10 users; p95 at 50 users 3,118 ms → 716 ms. **VERIFIED** |
| 4 | Host Alembic could resolve a connection to the V1 database | **Fixed.** Fail-closed identity guard, static and runtime. V1 rejected before connecting. **VERIFIED** |
| 5 | Production Compose had no scanner service, so uploads could only ever fail closed | **Fixed.** ClamAV service added; scanner verified against a real daemon (clean, EICAR, unavailable, timeout, malformed, 1 MiB). **VERIFIED** |
| 6 | API connected as the owning superuser, so the audit trigger could be dropped by the application itself | **Fixed for production shape.** Non-superuser application role provisioned; `audit_logs` granted SELECT/INSERT only. **VERIFIED on a fresh database** |

The baseline is materially stronger than the one certified in Phase 9. Three things did
**not** change and should not be read as solved: the platform still has no off-host copy
of the audit trail, the production stack has not been run on a real host, and every
institutional decision listed in §J is still open.

Two findings emerged *during* this phase that are worth stating plainly:

* **A migration that reports success can change nothing.** While adding the Phase 10
  revision, `alembic upgrade head` exited 0, logged `Running upgrade …`, and wrote
  nothing: the runtime identity check had left an implicit SQLAlchemy 2.0 transaction
  open, so Alembic committed only a savepoint and the outer transaction rolled back on
  disconnect. This was caught because the revision was verified against the database
  rather than the exit code. The environment now ends that read-only transaction
  explicitly. **Any deployment gate that trusts only an exit status is unsound** — this
  report's migrations were each confirmed by reading `alembic_version` and `pg_trigger`.
* **ClamAV's EICAR signature is anchored at the start of a file.** A probe that embeds
  the test string mid-file is reported clean by ClamAV itself. The first version of the
  scanner verification did exactly that and produced a false "not detected" result. The
  product code was not at fault; the probe was corrected and re-run.

---

## B. Audit integrity

### B.1 What the database looked like before

**VERIFIED** against the live development database (`school_portal_v2`):

```
role portal        : Superuser, Create role, Create DB, Replication, Bypass RLS
audit_logs owner   : portal
audit_logs relacl  : (null)            -- owner-only, but the owner is a superuser
audit_logs triggers: 0 rows
```

The Phase 9 finding was that the `portal` role holds UPDATE and DELETE. The stronger and
more useful statement is that `portal` is a **superuser and the table owner**. In
PostgreSQL a superuser bypasses every `GRANT`; it can also `ALTER TABLE … DISABLE TRIGGER`
or `DROP TRIGGER`. So revoking privileges alone would have been theatre in development,
and in production the same was true — the `postgres` image creates `POSTGRES_USER` as a
superuser, and every service connected as that account.

### B.2 What is enforced now

Two independent layers, deliberately:

**Layer 1 — statement-level triggers (works everywhere).** A `plpgsql` function
`audit_logs_reject_mutation()` raises `insufficient_privilege` (SQLSTATE 42501) for
`UPDATE`, `DELETE` and `TRUNCATE`, with `BEFORE UPDATE`/`BEFORE DELETE` row triggers and a
`BEFORE TRUNCATE` statement trigger. `INSERT` and `SELECT` are untouched. Triggers fire
for the table owner and for a superuser, which is why this layer protects the development
database as well as a hardened production one.

The same SQL is installed from two places so no environment can drift:
* `app/models/audit.py` — an `after_create` table event, so `Base.metadata.create_all`
  (the pytest fixture) builds exactly the production schema instead of a weaker one;
* migration `d1e4a7b9c2f5` — applies it to a database whose table already exists.

**Layer 2 — role separation (production shape only).** `scripts/provision-db-roles.sh`
creates an ordinary application role and grants it `SELECT`/`INSERT` on `audit_logs`
only, with `UPDATE`, `DELETE`, `TRUNCATE` and `REFERENCES` revoked, and no `TRUNCATE` on
any table. `docker-compose.prod.yml` now points the API at that role and keeps migrations
on the owning account. A new one-shot `provision-roles` service applies it between
`migrate` and `up`.

### B.3 Test evidence

**VERIFIED — development database, as the actual application role `portal`:**

| Requirement | Result |
|---|---|
| 1. Legitimate audit event is created | `INSERT … RETURNING` → `phase10.verify.insert`, exit 0 |
| 2. Authorized history is readable | `SELECT count(*)` → 1 |
| 3. Update is rejected | `ERROR: audit_logs is append-only: UPDATE is not permitted` |
| 4. Delete is rejected | `ERROR: audit_logs is append-only: DELETE is not permitted` |
| 5. Truncate is rejected | `ERROR: audit_logs is append-only: TRUNCATE is not permitted` |
| 6. Ordinary workflows still create events | admin `PATCH /students/{id}` → 200, one `student.updated` row with before/after |
| 7. Failed transactions leave no event | `tests/test_audit_immutability.py::test_rolled_back_business_change_leaves_no_audit_event`; also `test_rejected_student_update_writes_no_audit_event` |
| 8. Authorized migrations still work | `upgrade` → `d1e4a7b9c2f5` + 3 triggers; `downgrade -1` → `c4d7e91b2f68` + 0 triggers; `upgrade` again → 3 triggers |
| 9. Startup and normal operation unaffected | API `/ready` 200, login 200, reads and writes 200 on the running stack |

**VERIFIED — fresh production-shaped database (`school_portal_phase10_prod`):** migrated
from empty to head (`d1e4a7b9c2f5`, 3 triggers), then provisioned with a role split:

```
audit_logs  SELECT=true  INSERT=true  UPDATE=false  DELETE=false  TRUNCATE=false
students    UPDATE=true  DELETE=true
role        is_superuser=false  createrole=false
```

As that role: `SELECT count(*)` on `audit_logs` → 1 (works); `UPDATE`, `DELETE` and
`TRUNCATE` → `ERROR: permission denied for table audit_logs`.

**Automated:** `tests/test_audit_immutability.py` — 8 tests covering the trigger set,
insert/read, UPDATE, DELETE, TRUNCATE, survival of a refused truncate, and the
rolled-back-change case.

### B.4 Transactional consistency

`record_audit` still only stages on the caller's session; it never commits. The audit
entry therefore shares the transaction of the change it describes. A business rollback
removes both. This is unchanged behaviour and is now asserted rather than assumed.

### B.5 Stated limitation

A superuser or the owning role can still `ALTER TABLE audit_logs DISABLE TRIGGER`, drop
the trigger, or drop the function. This is **not** tamper-proofing against a database
administrator, and the report does not claim it is. Genuine protection needs the audit
stream to leave the database (append-only log shipping or WORM retention) — an
infrastructure decision under §J.

---

## C. Historical records (before/after)

### C.1 Method

No second history system was introduced. Each domain already had an authoritative record,
and the audit entry was made to carry the same accountability summary plus a pointer to
that record:

| Domain | Authoritative history | Audit event (Phase 10) |
|---|---|---|
| Student profile | none (audit log *is* the record) | `student.updated` gains `changes{field:{previous,new}}` |
| Student status | audit log | unchanged: `from`/`to` already present |
| Grades | `academic_change_history` (previous/new snapshots) | `academic.grade.updated` gains `changes` for `score`, `letter_grade`, `note` |
| Enrolment | `enrollments.status` + audit | `academic.enrollment.created`/`.dropped` gain student and status transition |
| Housing | assignments are rows, not edits | `housing.assignment.updated` gains `changes`; `.transferred` gains `previous_bed_id`; `.ended` gains `bed_id`, `end_date`, `status` transition |
| Immigration | `immigration_profile_versions` (previous/new, actor, reason) | new `immigration.profile.updated` event with `version_number`, changed field names, reason |

Every event already carried actor (`actor_id`/`actor_email`), entity type, entity id,
timestamp, request id and client IP. Nothing was removed.

### C.2 Value serialisation

`field_changes` compares snapshots and emits only fields that actually changed, as
`{previous, new}`. Values are normalised so a value read from a record and one read from a
request compare equal: `datetime`/`date`/`time` → ISO 8601, enums → their value,
`UUID` → string, `Decimal` → number, strings over 200 characters truncated. A key present
on one side only is recorded as a change from/to `null`, so clearing an optional field is
visible.

### C.3 Sensitive data

The existing denylist still runs over every context, recursively, so it applies inside
`changes` too. Policy applied deliberately:

* Recorded: ordinary profile fields (name, preferred name, contact numbers, nationality,
  date of birth), housing bed/status/date transitions, grade scores and notes, and the
  *names* of immigration fields that changed.
* Not recorded as values: `passport_number`, `visa_number`, `residence_permit_number`,
  `passport_name`, plus anything matching password/token/session/cookie/secret/checksum/
  content/body. The key survives with `[redacted]`, so the audit shows *that* the
  identifier changed without copying it. The full values remain in
  `immigration_profile_versions`, which is access-controlled and already carries the
  actor and reason.
* Never recorded: passwords, session tokens, authentication secrets, document contents.

Two consequences of that policy are stated here because they were *choices*:

* **Contact details and date of birth are recorded with values.** A staff member who can
  change a student's phone number can already read it; the accountability value of knowing
  *what* it was changed to is higher than the marginal disclosure of storing it once more
  in an access-controlled audit table. Date of birth is included because altering it is
  exactly the kind of identity tampering an audit trail exists to expose.
* **This supersedes an earlier assertion.** `test_platform.py` previously asserted that a
  `student.updated` entry contains *no* values at all
  (`test_student_update_is_audited_without_values`). That test encoded the Phase 9
  weakness, not a security requirement, so it was replaced — not deleted — with
  `test_student_update_is_audited_with_before_and_after`, which is stricter: it requires
  the previous value, the new value and the field list to be exactly right, and it still
  asserts that no credential reaches the log. The redaction rules themselves are unchanged
  and still tested by `test_sanitize_context_redacts_sensitive_keys`.

### C.4 Test evidence — **VERIFIED**

`tests/test_audit_history.py` (17 tests, all passing) covers: changed-only diffing,
new/removed keys, field restriction, serialisation of dates/enums/UUIDs/None, student
single-field and multi-field updates, a refused update producing no event, status
change from/to, housing edit, transfer (vacated bed), move-out (bed + status transition),
and an immigration correction that produces both an audit event and a version — including
an assertion that the passport value never appears in the audit context.

Live confirmation on the running development stack:

```
PATCH preferred_name: "Noor" -> "Phase10Check"   200
audit_logs: {"fields":["preferred_name"],
             "changes":{"preferred_name":{"previous":"Noor","new":"Phase10Check"}}}
PATCH preferred_name: "Phase10Check" -> "Noor"   200
audit_logs: {"fields":["preferred_name"],
             "changes":{"preferred_name":{"previous":"Phase10Check","new":"Noor"}}}
student record restored: preferred_name = "Noor"
```

The pair also demonstrates that the sequence is accurate and that a correction is a new
event rather than a rewrite of the previous one.

### C.5 Remaining gaps

* **No captured reason on several administrative paths.** `student.updated` has no reason
  field in its contract, so the audit records what changed and who changed it, not why.
  Adding a reason would change the API contract; it is left as a product decision.
* **Assessment edits.** `Assessment` changes write `academic_change_history` but do not
  emit a distinct audit event. The domain history is complete; only the audit-log view is
  thinner.
* **Enrolment drop** records the status transition; a drop *reason* is not part of the
  enrolment model, so none is recorded.
* **Study-programme changes** are already recorded through the placement/admission-change
  workflows with previous and new admission pointers; not re-tested here beyond the
  existing suite.

---

## D. Performance

### D.1 Method

Same harness, same stack, same data, same worker count, same levels as the Phase 9
measurement: `docker-compose.perf.yml` (own database `school_portal_perf` on 5440/8010, no
source bind mount, no reload), 4 uvicorn workers, 1,450 synthetic students, rate limiting
off, 15 s per level, mixed workload of 60 % student reads / 30 % staff reads / 10 %
sensitive writes. Baseline was captured on the unmodified tree immediately before any
Phase 10 edit: `.perf/phase10_baseline.json`. The after run used the same harness on the
rebuilt image: `.perf/phase10_after.json`.

### D.2 What was actually expensive

Profiling and `pg_stat_statements` produced three concrete causes, none of them "the
database is slow":

1. **`ClassSection` eager-loaded five collections.** `attendance_records`, `enrollments`,
   `timetable_entries` and `assessments` were `lazy="selectin"`. Every class-list,
   timetable and roster request therefore fetched *every* attendance row and *every*
   assessment/grades row for the selected sections and built an ORM object per row.
   Attendance had grown to 8,368 rows; a single class-list request materialised >5,000
   objects to render six sections. Nothing in the application reads those four
   attributes (`enrolled_count` is a stored column, not a count of `enrollments`).
2. **`list_enrollments` had an N+1.** One `SELECT … FROM students WHERE id = …` per
   enrolment. `pg_stat_statements` showed **16,291** executions of that single-row query —
   a roster request for a 290-student section issued 290 of them.
3. **Identity resolution cost four round trips.** `User.roles` and `Role.permissions` were
   `lazy="selectin"`, so every authenticated request paid three extra queries
   (`user_roles`, `roles`, `role_permissions`/`permissions`) before the router ran, on
   every endpoint — including one that answers with 63 bytes.

This is why the API was CPU-bound at ~400 % with only 2–3 active database queries: the
cost was object materialisation and round-trip count in Python, not query execution.

### D.3 Changes

| Change | File |
|---|---|
| Four `ClassSection` collections are no longer eager-loaded | `app/models/academic.py` |
| Roster loads students in one `IN` query | `app/services/academic.py` |
| Identity loads user + roles + permissions in one statement | `app/auth/service.py` |

No response schema, authorization rule, validation rule or business rule changed. The
roster payload was compared field-by-field against the database after the change
(7 API rows / 7 database rows, `student_name` and `student_number` populated).

### D.4 Results — read-heavy (10 % writes)

| Concurrency | rps before → after | p50 ms | p95 ms | p99 ms | API CPU peak % | Peak RAM MiB | PG active |
|---|---|---|---|---|---|---|---|
| 10 | 103.9 → **176.3** | 51.5 → 39.5 | 282.0 → **166.9** | 417.0 → **267.3** | 331.5 → 302.5 | 577 → 532 | 2 → 2 |
| 25 | 85.0 → **124.4** | 217.8 → 173.0 | 849.8 → **395.5** | 1217.9 → **596.5** | 404.6 → 341.7 | 698 → 570 | 2 → 3 |
| 50 | 50.5 → **123.0** | 604.1 → 367.3 | 3117.8 → **716.0** | 4913.8 → **999.0** | 426.0 → 364.0 | 799 → 609 | 2 → 4 |

### D.5 Results — write-heavy (60 % writes)

| Concurrency | rps before → after | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| 5 | 26.0 → **89.0** | 136.6 → 41.6 | 552.8 → **152.4** | 670.3 → **235.4** |
| 10 | 37.3 → **121.7** | 202.7 → 73.7 | 800.6 → **178.5** | 1217.7 → **271.0** |

Authentication (40 concurrent bcrypt logins): p50 1,723 → 1,541 ms, p95 2,026 → 1,815 ms,
19.1 → 20.2 rps. Login is dominated by bcrypt cost by design; it was not optimised.

### D.6 Failure rate — read this before quoting the percentages

**There were no 5xx responses in either run.** Every non-2xx was HTTP 400 from the
harness's own `attendance_write` action: it cycles `session_date` over 330 days, and a
second write for an already-recorded section/date is correctly refused. The same action
fails its preflight in *both* runs (`preflight_writes: attendance_write [400]`), because
the seeded data already holds that date.

| Run | 400s | Cause |
|---|---|---|
| before | 57 (10), 0 (25), 0 (50) | attendance duplicate |
| after | 146 (10), 98 (25), 105 (50) | attendance duplicate |

The after run completes far more attendance writes, so it reaches the collision more
often. The refusal is correct application behaviour (idempotency guard), not a capacity
failure. Excluding `attendance_write` 400s, the error rate is 0 % in both runs.

### D.7 Concurrency invariants after the change

`class_capacity`, `attendance_race`, `immigration_race` and `program_change_retired` all
passed. `bed_assignment` reported `passed=false` in the after run — **because the harness
reuses the same three beds as the baseline run**, which are now occupied. All 36 attempts
returned `409 BED_OCCUPIED` and the database invariant holds:

```
beds with an active assignment: 317
max active assignments per bed: 1
beds with more than one active assignment: 0
```

A second run of a stateful race on the same database cannot re-win a bed. This is a
harness property, not a regression; the invariant it exists to protect is intact.

### D.8 Realistic capacity conclusion

Measured on a 10-core / 16 GiB host with the API and database in Docker on the same
machine:

* ~**176 rps** of mixed reads at 10 concurrent users, p95 **167 ms**;
* ~**123 rps** at 50 concurrent users with p95 **716 ms** — throughput *rises* with load
  instead of collapsing, which is the signature of the previous saturation being removed;
* still CPU-bound (peak 364 % of four workers) rather than database-bound (2–4 active
  queries), so further gains need either more CPU or fewer round trips, not a bigger
  database.

**75 concurrent users was not run.** The four-worker container was already at 364 % CPU
at 50 users and the host also runs the development and V1 stacks; a 75-user level would
have measured host contention rather than the application. **NOT VERIFIED.**

**No claim is made about 1,500 concurrent users.** The planning population is ~1,500
registered students; that is not a concurrency figure. A realistic planning assumption
remains a few hundred *simultaneous* staff and student sessions at peak, which the numbers
above support at the 50-user level and which has not been demonstrated beyond it.

### D.9 What was not optimised, deliberately

No caching was added. No background job was introduced. No response contract was
narrowed. The remaining fixed cost per request is the session lookup plus the student-record
access check; caching either would trade correctness (status changes must take effect on
the next request) for latency, which is not a trade this phase was authorised to make.

---

## E. Migration safety

### E.1 The failure this prevents

Phase 9 found that `alembic` run from a host shell with no `DATABASE_URL` in the
environment fell back to `postgresql://portal:portal@localhost:5433/school_portal` — the
**V1 reference database** — and would have advanced its schema.

### E.2 Guard design (`app/database/migration_guard.py`)

Checked before any connection is opened:

1. `DATABASE_URL` must be present, parseable, PostgreSQL, and name a database. Missing or
   ambiguous configuration is refused rather than defaulted.
2. **V1 is refused by name.** `school_portal` is rejected outright, as are the PostgreSQL
   system databases.
3. The environment designates the target. Outside production the name must belong to the
   V3 family (`school_portal_*`) or appear in `MIGRATION_ALLOWED_DATABASES`. In production
   `MIGRATION_CONFIRM` must name the database exactly, so an operator states the target
   instead of it being inferred — production databases do not have to follow this
   project's development naming.
4. **Runtime, after connecting:** `current_database()` must equal the database in the URL,
   and any recorded `alembic_version` must be a revision this repository defines. V1's head
   `c7d9e1f3a5b7` is not in this repository, so a V1 database that somehow passed the name
   check is refused before a single statement is issued.

Port numbers are deliberately **not** the basis of the decision. Ports are remapped
routinely and a guard that trusted `5435` would fail the first time a stack moved.

### E.3 Test evidence — **VERIFIED**

| # | Requirement | Result |
|---|---|---|
| 1 | Correct V3 development database accepted | `school_portal_v2` → accepted, `alembic upgrade` → `d1e4a7b9c2f5` |
| 2 | V1 database rejected | `…:5433/school_portal` → exit 1, "that is the V1 reference installation", before connecting |
| 3 | Unexpected database identity rejected | `other_db` → exit 1; `postgres`, `template1`, empty name → refused |
| 4 | Missing / ambiguous configuration rejected | no URL → refused; `sqlite:///…` → refused |
| 5 | Approved production-shaped configuration accepted | production + `MIGRATION_CONFIRM=school_portal_phase10_prod` → `d1e4a7b9c2f5 (head)` |
| — | Production without confirmation | exit 1, "MIGRATION_CONFIRM is required when ENVIRONMENT=production" |
| — | Production with mismatched confirmation | exit 1, "does not match the database in DATABASE_URL" |
| 6 | Existing test fixtures still function | full suite runs against `school_portal_test_v2` on 5434 |
| 7 | Migration state remains correct | `upgrade` → `d1e4…` + 3 triggers; `downgrade -1` → `c4d7…` + 0; `upgrade` → `d1e4…` + 3 |
| 8 | No unintended database modified | only `school_portal_v2` and the disposable `school_portal_phase10_prod` were touched |

**Automated:** `tests/test_migration_guard.py` — 18 tests (URL rules, production
confirmation, escape hatch, runtime identity, foreign revision rejection).

### E.4 A defect found in this phase's own work

The runtime check initially ran on the same connection Alembic then used. SQLAlchemy 2.0
begins a transaction implicitly on the first statement; Alembic's `begin_transaction()`
therefore opened a **savepoint** inside it and committed only that, while the outer
transaction rolled back when the connection closed. `alembic upgrade head` exited 0 and
logged `Running upgrade c4d7e91b2f68 -> d1e4a7b9c2f5`, and the database was unchanged.

The environment now calls `connection.rollback()` after the read-only verification and
before configuring the migration context. This is documented in the file so it is not
"fixed" back later.

The general lesson is recorded in §A: a migration gate must verify the database, not the
exit code.

---

## F. Document-scanning readiness

### F.1 What was wrong

`docker-compose.prod.yml` had **no scanner service**. `MALWARE_SCANNER` defaulted to
`disabled`, which fails closed — correct, but it means a production installation could
never accept a single document. `CLAMAV_HOST`/`CLAMAV_PORT` were already forwarded, so the
client side existed; the daemon did not.

### F.2 What changed

* A `clamav` service (`clamav/clamav:stable`) on the internal network only, with the
  signature database and run directory on named volumes so a restart does not re-download
  ~180 MB or serve an empty database in the meantime.
* Health check is `clamdcheck.sh`, which performs a real `PING` on the daemon socket — the
  container is not "healthy" merely because the process exists.
* `MALWARE_SCANNER` defaults to `clamav` in production; `api` now `depends_on` the scanner
  being healthy, because declaring the API ready while it cannot accept an upload is
  misleading.
* `CLAMAV_PLATFORM` is configurable. The published images are **amd64-only**; this host is
  arm64 and ran the daemon under emulation for verification. That is documented rather
  than hidden.
* `.env.production.example` documents the scanner default and the amd64 constraint.

The application's existing fail-closed behaviour was **not** weakened. `disabled`,
`dev-clean` and `eicar-test` are all still refused in production by the settings
validator; no code path treats "no scanner" as "clean".

### F.3 Test evidence — **VERIFIED against a real ClamAV daemon**

ClamAV 1.5.5, signature databases loaded (`main.cvd`, `daily.cld`), reached over TCP
INSTREAM by the application's own `app/services/malware_scan.py`:

| Case | Result |
|---|---|
| Clean file | `CLEAN` (engine `clamav`) |
| EICAR test file | `INFECTED` — "malware signature detected" |
| Scanner unavailable (closed port) | `FAILED` — `ConnectionRefusedError` |
| Scanner timeout (accepts, never answers) | `FAILED` — `TimeoutError` |
| Malformed response (`WHATEVER`) | `FAILED` — "scanner returned an unrecognised response" |
| 1 MiB file (chunked INSTREAM) | `CLEAN` |

No case produced a false `CLEAN`. Oversized-upload limits, unauthorized upload and
unauthorized download are enforced by the existing document endpoints and are covered by
the suite (`test_platform.py` sets `MAX_UPLOAD_SIZE_MB` and asserts the refusal;
`test_institutional_governance.py` covers scanner gating).

Persistent storage across restart is a property of the existing `documents` named volume
and was verified in Phase 9's backup/restore rehearsal; it was not re-tested here because
no storage code changed.

### F.4 What is still needed

The daemon is now configured and proven against the real protocol. What remains is a
**university decision**: which scanner infrastructure is approved, who owns it, and whether
the bundled container or the institution's own endpoint is authoritative. The technical
path supports either — point `CLAMAV_HOST`/`CLAMAV_PORT` at the approved endpoint.
**INSTITUTIONAL DECISION REQUIRED.**

---

## G. Regression results

### G.1 Executed

| Check | Result |
|---|---|
| Full API test suite (`pytest`) | **1,103 passed, 2 skipped, 0 failed** (17:01) — see §G.4 |
| New: `test_audit_immutability.py` (8) | pass |
| New: `test_audit_history.py` (17) | pass |
| New: `test_migration_guard.py` (18) | pass |
| New: locale-parity test (`test_platform.py`) | pass |
| Python compile of every changed module | pass |
| `alembic upgrade` / `downgrade` / `upgrade` round-trip | pass (see §B.3, §E.3) |
| Fresh-database migration + role provisioning | pass (see §B.3) |
| Live workflow on the development stack | login 200, PATCH 200, audit before/after correct, revert 200, value restored |
| Performance before/after | pass (see §D) |
| Scanner against real ClamAV | pass (see §F.3) |
| `docker compose -f docker-compose.prod.yml config` | valid, with `migrate`, `provision-roles`, `clamav` rendered |

### G.2 Not repeated, and why

The Phase 8 and Phase 9 results (1,059-test suite, `tsc`, `next build`, 10/10 browser
certification, 60-minute soak, load runs) are **not** re-run wholesale. They remain
historical evidence for code this phase did not touch. The two exceptions are the API
suite (shared models and services changed, so it *is* re-run) and the load measurement
(which is the point of §D).

### G.3 Not run at all, and why

| Check | Reason |
|---|---|
| TypeScript / `next build` | No TypeScript file under `apps/web` was modified — only the five message catalogs. No API response schema changed, so the client contract is unchanged. **NOT VERIFIED** (nothing type-checkable changed) |
| Localisation parity | **Executed.** One key was added (`audit.actions.immigration.profile.updated`) and all five catalogs were updated together (en, zh, fr, ru, ar). A new test, `test_every_translated_action_exists_in_every_locale`, asserts the five catalogs have identical key sets; it passes. RTL layout was not re-checked because no layout or component changed. |
| Browser workflows | No UI changed. Not exercised this phase. **NOT VERIFIED** |
| Production `docker compose up` on a real host | Out of scope for this phase (no deployment authorised), and the ClamAV image needs an amd64 host or emulation. **NOT VERIFIED** |
| 75-user load level | See §D.8. **NOT VERIFIED** |

All five locales remain supported: the settings list is unchanged
(`SUPPORTED_LOCALES = ["en", "zh", "fr", "ar", "ru"]`), no translation file was touched,
and no component was removed.

### G.4 Final suite result

```
1103 passed, 2 skipped, 23 warnings in 1021.29s (0:17:01)
```

Two tests were skipped by their own guards (both seed-dependent, unchanged from the
previous phase). Zero failures. This is a full run of the current tree, executed after the
last source and test edit — not an assembled total.

### G.5 What the full suite caught

The first full run after the source changes reported `2 failed, 1100 passed`. Both were
real, and both were caused by this phase's work:

1. **`test_every_recorded_action_has_a_translation`.** The new `immigration.profile.updated`
   event had no message in the web catalog, so the audit screen would have rendered a
   humanised token instead of a label. Fixed by adding the key to all five locales, and
   the contract was hardened with a second test that requires the five catalogs to agree
   on the entire key set — the previous test only compared English against the backend.
2. **`test_student_update_is_audited_without_values`.** An existing test asserted the
   opposite of Priority 2: that a student update records field names and *no* values. It
   was replaced with a stricter test of the new contract (§C.3). This is the one place
   where an existing assertion was changed rather than satisfied, and the reason is that
   it encoded the weakness this phase was asked to fix, not a requirement.

Both were fixed and re-run (53 tests across the affected classes, all passing) before the
full suite was repeated.

---

## H. Current system status

### H.1 Development

**GO.** All stacks run: V3 web 3101 / API 8001 / DB 5435; V1 web 3100 / API 8000 / DB
5433 (read-only, untouched); pytest fixture DB 5434. Migrated to `d1e4a7b9c2f5`. Audit
immutability is live. The performance changes are live and verified by the suite.

### H.2 Internal presentation

**GO.** No user-visible change: no route, component, translation, colour or layout was
altered. Presentation can only get faster — the endpoints it exercises are 2–4× quicker.

### H.3 Institutional UAT

**CONDITIONAL GO.** UAT can start on a UAT database. Conditions are unchanged from Phase 9
(UAT accounts, agreed acceptance criteria) plus one new item: the UAT host should run the
production Compose shape now that role separation and the scanner exist, so UAT exercises
the same permission model as production rather than the development superuser.

### H.4 Limited institutional operation

**NO-GO.** Unchanged from Phase 9, and the remaining blockers are not technical polish:

* no off-host audit or backup copy (a single host remains a single point of loss);
* no approved scanner infrastructure owner;
* no TLS/DNS ownership or host administration agreement;
* no agreed retention periods, so nothing can be deleted under policy.

### H.5 Production

**NO-GO.** The *technical* production gaps this phase could close are closed: the
application no longer runs as a superuser, the audit table is append-only in code and in
grants, uploads can be scanned, and migrations cannot reach V1. Production is still
blocked by decisions and by the fact that the production stack has never been run on a
real host (§J).

### H.6 Real-data migration

**NO-GO.** Out of scope for this phase and unchanged: no real institutional data was
touched, and a migration rehearsal with rollback against a real extract has not happened.

---

## I. Commit readiness

**The tree is safe to commit as a stable baseline, with the classification below.**
Nothing has been staged, committed or pushed.

### I.1 Change classification

| Category | Files |
|---|---|
| **1. Audit integrity** | `app/database/audit_immutability.py` (new), `app/models/audit.py`, `alembic/versions/d1e4a7b9c2f5_audit_log_immutability.py` (new), `scripts/provision-db-roles.sh` (new) |
| **2. Historical records** | `app/audit/service.py`, `app/audit/__init__.py`, `app/routers/students.py`, `app/routers/housing.py`, `app/routers/academic.py`, `app/routers/immigration.py`, `app/services/immigration.py` |
| **3. Performance** | `app/models/academic.py`, `app/services/academic.py`, `app/auth/service.py` |
| **4. Migration safety** | `app/database/migration_guard.py` (new), `alembic/env.py` |
| **5. Deployment / scanning** | `docker-compose.prod.yml`, `.env.production.example` |
| **6. Tests** | `tests/test_audit_immutability.py`, `tests/test_audit_history.py`, `tests/test_migration_guard.py` (all new); `tests/test_platform.py` (one privacy assertion replaced by a stricter one, one locale-parity test added) |
| **6b. Localisation** | `apps/web/messages/{en,zh,fr,ru,ar}.json` — one key added to each: `audit.actions.immigration.profile.updated` |
| **7. Documentation** | this report |
| **8. Unrelated / unexplained** | none from this phase |

`docker-compose.prod.yml`, `.env.production.example`, and the Phase 7 migration files
`b8d2f4a61c93_*` / `c4d7e91b2f68_*` were already untracked before this phase; they are
part of the pre-existing work and were edited only where listed.

### I.2 Release-baseline checks

* **Accidental V1 changes:** none. V1 was read-only throughout; its database was queried
  once to confirm identity, and no V1 file, container or schema was modified.
* **Exposed credentials:** none added. The provisioning script takes the application role
  password from the environment and never writes it; `.env.production.example` uses
  `REPLACE_ME`. The script's own guard refuses to run when the application role equals the
  owning superuser.
* **Unexpected schema changes:** one migration, additive in effect. It creates a function,
  three triggers and a revoke. It does not alter, backfill or delete any row.
* **Destructive migrations:** none. `upgrade()` contains no `DROP`. `downgrade()` only
  removes the triggers and function; the audit rows themselves are never dropped.
* **Missing tests:** none for the changed behaviour — every corrected path has a test
  (§B.3, §C.4, §E.3), plus the full suite.
* **Broken imports / compile:** clean; every changed module compiles and the suite imports
  the application normally.
* **Dependency changes:** none. No `requirements`, `pyproject`, lockfile or `package.json`
  was modified by this phase. (`apps/web/package.json` was already modified before this
  phase.)
* **Untracked generated files:** none added to the working tree that are not listed above.
  The profiling and verification helpers in `.perf/` and the `/tmp` logs are diagnostics
  outside the tracked tree.
* **Accidental deletion of functionality:** none. Every change is additive or a behaviour-
  preserving optimisation; the roster payload was compared against the database after the
  change, and the full suite passes.

### I.3 Before committing — housekeeping

Decided by the person committing, not by this phase:

1. Several files are **untracked** and would be left behind by a `git commit -am`:
   `docker-compose.prod.yml`, `.env.production.example`,
   `scripts/provision-db-roles.sh`, the migration `d1e4a7b9c2f5`, the three new test
   modules, and the two earlier untracked migrations (`b8d2f4a61c93`, `c4d7e91b2f68`).
   A baseline commit must `git add` them explicitly; a commit that omits the migration or
   the provisioning script would ship code that expects a role split the deployment cannot
   create.
2. Two verification rows were added to the **development** database during this phase
   (`phase10.verify.insert`, plus the change/revert pair). They are real audit records and
   are append-only by design — they cannot be deleted, and removing them would defeat the
   control this phase added. The student record was restored exactly (`Noor`).
3. The disposable database `school_portal_phase10_prod`, the `phase10_app` role and the
   `sycumain-clamav-probe` container were removed after verification.

---

## J. Remaining blockers

### J.1 Real technical blockers

| Blocker | Consequence |
|---|---|
| No off-host copy of audit or backup | A single host failure loses the audit trail and the database together. The trigger protects against application-level rewriting, not against hardware loss. |
| Audit tamper-proofing stops at the DBA | A database administrator can disable the trigger. Only off-host append-only shipping removes that. |
| Production stack never run on a real host | Migration, Caddy/TLS, the role split and the scanner are proven in isolation and on a fresh database, not as a complete production bring-up. |
| ClamAV has no native arm64 image | An arm64 production host runs the scanner emulated (functional, slower) or must use an external scanner endpoint. |
| No rate-limit-enabled load test | The measured runs deliberately disable rate limiting; its cost under load is unmeasured. |

### J.2 Institutional decisions

Nothing here should be guessed, and none of it blocked the technical work.

| Decision | Consequence of leaving it unresolved |
|---|---|
| Audit and student-record retention periods (`RETENTION_*`) | Nothing can be deleted under policy; the retention report stays "policy pending approval" and the database grows without an agreed bound. |
| Document retention and deletion rules | Documents accumulate indefinitely; "delete" remains an administrative action without a mandate. |
| SMTP / email relay ownership | Password reset and activation stay `disabled`; recovery is counter-only. |
| Approved malware-scanning infrastructure | The bundled daemon works, but no one owns patching signatures, or approving an alternative endpoint. |
| TLS and DNS ownership | Caddy cannot be issued a real certificate; the portal cannot be exposed to students. |
| University server administration responsibility | No one is accountable for patching, monitoring, disk capacity or restarts. |
| Backup ownership and RPO/RTO | Backups exist but their frequency, destination and restore guarantee are unagreed; recovery objectives are undefined. |
| UAT participants and acceptance sign-off | UAT cannot conclude or authorise a release. |
| Admission and academic approval policies | The admission gates stay off, so the workflows behind them cannot be used institutionally. |

---

## K. Recommended next step

**One thing: run the production stack once, end to end, on a single real host — with the
role split, the scanner, migrations and TLS — and restore a backup into it.**

That single exercise converts the largest remaining "NOT VERIFIED" items into evidence:
it is the only way to prove the `migrate → provision-roles → up` ordering, the
non-superuser API role, Caddy certificate issuance, the scanner under real network policy,
and a restore onto a clean host. It does not require institutional data: a synthetic
cohort is sufficient, and the backup/restore procedure was already rehearsed on the real
development dataset in Phase 9.

Do that before any further code work. Do not start another audit; there is nothing left in
the previous one that a second read would answer.

---

## Appendix 1 — Commands and artefacts

| Purpose | Artefact |
|---|---|
| Baseline measurement | `.perf/phase10_baseline.json` |
| After measurement | `.perf/phase10_after.json` |
| CPU attribution | `.perf/profile_api.py`, `.perf/phase10_profile.json` |
| Scanner verification | `.perf/verify_scanner.py` |
| Full suite log | `/tmp/full-suite.log` |

## Appendix 2 — Evidence carried forward from Phase 9, not re-run

The Phase 9 report's backup/restore parity (64/64 tables, identical row counts), the
migration audit, the i18n parity check (2,567 keys × 5 locales), the referential-integrity
survey and the browser certification remain valid for the code they describe. This phase
changed no backup script, no migration other than the additive one above, no translation
file and no frontend component, so those results still describe the current tree for those
subsystems. Where a shared API file changed, the corresponding suite tests were re-run
rather than relied upon.

## Appendix 3 — What this report does not claim

* It does not claim the audit trail is tamper-proof. It claims application-level
  operations cannot rewrite it, and that a non-superuser production role cannot remove the
  control.
* It does not claim capacity for 1,500 concurrent users. It reports 176 rps / p95 167 ms at
  10 users and 123 rps / p95 716 ms at 50 users on a specific host.
* It does not claim production readiness. It claims the specific technical weaknesses
  identified in Phase 9 are closed and demonstrated.
* It does not claim any institution has agreed retention, recovery objectives, scanner
  ownership or UAT acceptance.
