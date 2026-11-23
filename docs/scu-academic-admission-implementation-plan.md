# SCU — Academic Admission Architecture: Phased Delivery Plan (Revision 2)

**Status:** planning only; no code, migration, schema, data or environment change performed.
**Source design:** `docs/scu-academic-admission-architecture.md` (Revision 3).
**Scope:** the nine-step sequence in §12 of the design, expanded into phases with acceptance
criteria, completion conditions, independence analysis, verification requirements, rollback points,
decision gates and release rules.
**Approval:** pending. No phase may start before its entry criteria and decision gates are met.

---

## 1. Planning rules

These apply to every phase and are not repeated in each one.

1. **Design precedes schema; schema precedes behaviour.** No phase may add a table or column that a
   later phase has not yet justified, and no phase may read a table before the phase that owns it.
2. **No backfill, ever.** No script, import, heuristic or migration creates admission episodes,
   confirmations, placements or pointers for existing students. Migration is a human workflow
   (Phase 2), not a data job.
3. **Additive migrations only.** Every schema change in Phases 0–7 is additive (new tables, nullable
   columns, indexes, triggers). Destructive change is confined to Phase 8b and needs its own
   approval. Downgrades are not a rollback strategy once real rows exist.
4. **Rollback is a feature switch or a release revert, not data surgery.** Each phase ships behind a
   server-side setting so behaviour can revert while written data stays intact. Settings follow the
   existing `apps/api/app/config/settings.py` `BaseSettings` pattern; they never grant permission,
   they only enable behaviour, and permissions still decide authorization.
5. **Forward fix for bad data.** Once a phase has written records, corrections go through the
   audited correction workflows (Phases 5 and 7), never through ad-hoc SQL or a row delete.
6. **Academic history is immutable.** No phase may update or delete `enrollments`,
   `attendance_records`, `grades`, `assessments`, `timetable_entries` or `academic_change_history`
   rows. Each phase's tests assert this with before/after counts and value snapshots.
7. **Every phase is bilingual in tests.** Backend acceptance is executed through
   `make test-api`; UI-bearing phases additionally require `make typecheck`, `make lint-web`,
   `make i18n`, `make build`, and `make e2e` where the flow is browser-visible. Five locales are
   checked in the same phase that introduces the strings.
8. **Environment discipline.** Development uses `make dev` / `make dev-migrate`; the isolated local
   production-shaped stack uses `make prod-verify`; institutional production is untouched by this
   plan. No phase touches the production-verification environment.
9. **One phase, one release.** A phase is not "done" until its exit gate passes on the target
   environment; phases are not bundled to save a release.
10. **Audit before convenience.** Every mutation writes its audit entry in the same transaction as
    the data change. A phase whose audit assertions fail is not releasable.
11. **Synthetic data only.** Every test, probe, fixture and demonstration uses generated records in a
    disposable database. No institutional student record, real passport/visa value, production
    extract or anonymised copy is used in any phase. §14.4 defines the fixture rules.
12. **Nothing irreversible before P8b.** Phases 0–8a add tables, rows, indexes and code paths; none
    drops a column, rewrites an existing academic record or deletes a row. The single destructive
    operation in this plan is P8b, which is explicitly optional and separately authorized.
13. **Existing behaviour is preserved.** Each phase must leave the current academic/timetable,
    onboarding, profile, immigration and document flows working. Phases that replace a write path
    prove flag-off parity with the pre-phase behaviour before enabling the new path. Existing test
    expectations are not weakened to accommodate a phase; a changed expectation is a reviewed
    behaviour change, not a test edit.
14. **The production-verification environment is untouched.** No phase starts it, migrates it,
    reseeds it, or uses it as a test target. Development uses `make dev` / `make dev-migrate`;
    browser checks use the disposable stack behind `make e2e`.

### 1.1 Practical path, tracks and independent delivery

Minimum credible release, if capacity is limited: **P0 → P1 → P2**. That delivers admission episodes,
the lifecycle guard and verified historical intakes — the part every later phase depends on. P5 is
delivered independently of the admission core and can start immediately after P0. P8b (dropping
columns) is deferrable indefinitely; the system is correct and complete without it.

| Track | Phases | Entry point | Why it can be delivered separately |
|---|---|---|---|
| A — admission core | P0 → P1 → P2 | — | Owns episodes, statuses, verification acts and the pointer |
| B — intake dates | P0 → P5 | P0 | Touches only `academic_periods`, its correction table and the academics screen |
| C — delivery | P1 → P3 → P4 | P1 | Reads admission status, never verification acts |
| D — immigration | P2 → P6 | P2 | Reads the pointer and trust states; no episode writes |
| E — corrections | P2, P4 → P7 | P2/P4 | Two endpoints and two dialogs over existing tables |
| F — retirement | P6, P7 → P8a → P8b | P8a stable | P8a is a route-level block; P8b is schema-only |

Rules for parallel work:

- Tracks B, C and D may run concurrently once their entry phase is released: they write different
tables and register different routes.
- Each phase gets **its own Alembic revision**, ordered by dependency, even when two phases are built
  in parallel. Two tracks must never share a revision file.
- Shared files — permission constants, the five locale catalogs, OpenAPI export and generated types —
  are the real merge-conflict surface. P0 lands the permission codenames; P1 lands the status and
  error keys; later phases append to the same catalogs in dependency order.
- A track that is paused must ship with its flag in the safe position (off, or `LEGACY`), and its
  tables stay inert. Nothing in a paused track blocks another track's reads.

---

## 2. Phase map

| Phase | Name | Track | Size | Can start after | Primary flag / switch | Reversible |
|---|---|---|---|---|---|---|
| P0 | Schema foundation and permissions | A | M | — | none (inert) | Yes (drop empty objects) |
| P1 | Admission episodes and registration | A | L | P0 | `ADMISSIONS_WRITE_ENABLED` | Yes |
| P2 | Migration verification and trust | A | L | P1 | `ADMISSION_MIGRATION_CONSOLE_ENABLED` | Yes |
| P3 | Placement and earlier-intake authorization | C | M | P1 (P2 for migrated students) | `ADMISSIONS_WRITE_ENABLED` | Yes |
| P4 | Programme-change workflow | C | M | P3 | `ADMISSION_CHANGE_REQUESTS_ENABLED` | Yes |
| P5 | Intake date correction | B | S | P0 | `ADMISSION_DATE_CORRECTION_ENABLED` | Yes (data reversed by a new correction) |
| P6 | Immigration cohort switch | D | M | P2 | `ADMISSION_COHORT_SOURCE` | Yes (switch back; no data rewrite) |
| P7 | Correction workflows | E | M | P2, P4 | `ADMISSION_CORRECTIONS_ENABLED` | Yes |
| P8a | Retire direct writes | F | S | P6, P7 | `ADMISSION_DIRECT_WRITE_MODE` | Yes |
| P8b | Drop legacy projections | F | S | P8a + soak | none | **No** (restore from backup only) |

Size is relative complexity (S ≤ 1 sprint-equivalent of work, M ≈ 1–2, L ≈ 2+), not a calendar
commitment; no dates are proposed until owners are assigned. No phase other than P8b drops,
rewrites or deletes existing data, and P8b is not scheduled by default.

**Refinement to design §12:** admission creation, activation and status transitions are delivered
in P1 (together with the read surface), not deferred. P3 cannot create a placement without an
`ADMITTED`/`ACTIVE` episode, and P1's onboarding integration is the first real writer. This does not
change the dependency graph in §12; it makes the step-2 deliverable honest about its write paths.

---

## 3. Phase 0 — Schema foundation and permissions

**Objective:** every table, constraint, index, trigger and permission exists, and nothing reads or
writes it.

**Completion condition:** the revision applies and reverses on an empty database, every constraint
probe behaves as specified, permission seeding is idempotent, the existing suites are green, and no
application code path reads the new objects.

**Entry criteria:** architecture Revision 3 approved; a restorable backup exists for the target
environment; migration head is recorded.

**Work**

- One Alembic revision creating `academic_admissions`, `academic_admission_status_history`,
  `academic_placements`, `academic_admission_changes`,
  `academic_admission_verification_acts`, `academic_period_date_corrections`,
  `student_original_admission_history`; the `students.original_admission_id` column; the
  `program_offerings(academic_period_id, id)` unique key.
- All CHECKs, partial unique indexes and the seven triggers from design §3.2–§3.3.
- Permission rows for the twelve new codenames and their ADMIN/MANAGEMENT/TEACHER/STUDENT mapping,
  appended to the existing seed in `app/permissions/constants.py`.
- No service, router, schema or UI change. No data writes.

**Acceptance criteria**

1. `cd apps/api && .venv/bin/python -m alembic heads` returns exactly one head; the new revision is
   a single step from the previous head.
2. On a disposable database copy: `make dev-migrate` applies cleanly; a second run is a no-op.
3. On an empty database, upgrade → `alembic downgrade -1` → upgrade succeeds.
4. Constraint probes, each executed as raw SQL against the scratch database and expected to fail:
   second `ACTIVE` episode; `ADMITTED` while another episode is `ACTIVE`; earlier-intake placement
   without authorizer or reason; `VERIFIED` migrated row without both confirmations; two `PENDING`
   change requests of one type; clearing or replacing `students.original_admission_id` outside the
   correction flag; duplicate live episode for the same `(student, intake)`.
5. Positive probes succeed: `PENDING` beside `ACTIVE`; terminal history of many episodes; placement
   within the admission intake without a reason; revocation retaining the prior confirmation. A
   delete of an admission, placement, change or act is refused by trigger and is asserted as such.
6. `make test-api` and `make lint-api` pass with no changed expectations (schema is inert).
7. Permission seeding is idempotent: running the seed twice yields the same `role_permissions` rows.
8. `git diff` contains no application logic outside the migration, model declarations, permission
   constants and tests.

**Rollback point:** the phase is inert, so rollback is `alembic downgrade -1` while every new table
is empty, or simply reverting the release and leaving the additive schema in place. Do not downgrade
after P1 has written rows.

**Risks / notes:** the `ADMITTED` guard must be a trigger, not only an index; a reviewer should
confirm the migration's partial index predicates match design §3.2 exactly, because a wrong
predicate silently permits the state the whole design forbids.

**Decisions needed:** none.

---

## 4. Phase 1 — Admission episodes and registration

**Objective:** a student's admission becomes a real episode with a lifecycle, and registration uses
it.

**Completion condition:** flag-off onboarding and profile are indistinguishable from today; flag-on
lifecycle tests (including the concurrency case) pass; projections match the active episode; no
academic-history row changed; all five locales render the new statuses.

**Entry criteria:** P0 exit gate. `D7` (activation timing) has a recorded position — the default is
"`ACTIVE` may be set before the intake starts when no other episode is active".

**Work**

- Read endpoints: episode list for a student, with admitted vs current programme, status, origin and
  verification summary.
- Write endpoints: create episode (`initial_status`), status transitions, with the §2.2 guards and
  `SELECT … FOR UPDATE` on the student's episodes.
- `NEW_ADMISSION` origin, `verification_status = VERIFIED`, `verified_at = created_at`, and
  original-admission pointer set in the same transaction for a first episode.
- Status-history rows for every accepted transition; audit actions.
- Projection maintenance: `Student.program_id`, `major_id`, `program_offering_id` written only here.
- Onboarding integration behind `ADMISSIONS_WRITE_ENABLED`: intake select, offering filtered to
  intake, explicit `PENDING`/`ADMITTED`/`ACTIVE` choice, `PENDING` forced when an active episode
  exists.
- Student profile *Admissions* panel (history + prepared future episode).
- Five-locale strings for statuses, the pending-only explanation and error codes; OpenAPI export and
  generated types.

**Acceptance criteria** (design §10 scenarios 13–26, 61a, plus)

1. With `ADMISSIONS_WRITE_ENABLED=false`, onboarding and profile behave exactly as before; the
   existing suites `test_student_profile.py`, `test_student_program_offering.py`,
   `test_student_import.py` pass unmodified.
2. With the flag on: no active episode → `ACTIVE` accepted and `activated_at` set; active episode
   exists → `PENDING` accepted, `ADMITTED`/`ACTIVE` refused with `ADMISSION_MUST_BE_PENDING`,
   `PENDING → ADMITTED` refused, `PENDING → ACTIVE` refused.
3. Ending the active episode, then activating the prepared one, leaves exactly one `ACTIVE`.
4. Two concurrent activation requests produce one success and one 409; a raw second `ACTIVE` insert
   fails the index; a raw `ADMITTED`-while-`ACTIVE` update fails the trigger.
5. Creating an episode in an intake earlier than the active episode's intake is refused with
   `ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE`.
6. Every transition has exactly one status-history row and one audit entry with actor, timestamp and
   reason where required.
7. `Student.program_*` projections match the active episode and current placement after each write;
   a client payload containing them is ignored or refused.
8. No enrolment, attendance, grade, assessment or timetable row changes across the scenario suite
   (count and value snapshots).
9. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make types`,
   `make build` pass.
10. Arabic and Russian render the new statuses and the pending-only message without missing keys;
    the status chip is icon + label, not colour alone.

**Rollback point:** set `ADMISSIONS_WRITE_ENABLED=false` and redeploy. Onboarding reverts to the
legacy projection path, the Admissions panel becomes read-only or hidden, and episodes written during
the window remain as inert history. No episode, status-history row or audit entry is deleted. Code
revert is optional and independent.

**Risks / notes:** the legacy onboarding still writes `program_offering_id` directly; during P1 that
is the fallback path, not a second source of truth. Any drift between projections and episodes is a
P1 defect, not a data-cleaning task.

**Decisions needed:** `D7`.

---

## 5. Phase 2 — Migration verification and trust

**Objective:** existing students acquire a verified original admission through two independent human
confirmations, with no erasure and no inference.

**Completion condition:** a synthetic migrated student can be confirmed by two distinct roles,
revoked, re-confirmed and disputed without losing a single act; the pointer is set once and cannot
be cleared; no episode exists for any student who was not explicitly processed.

**Entry criteria:** P1 exit gate; `D1` (distinct confirmers) and `D3` (evidence standard) have
recorded positions — defaults are "distinct users enforced" and "evidence type + reference + note".

**Work**

- Verification queue (`GET /students?admission_verification=…`) covering unverified, revoked,
  disputed and no-admission students.
- Candidate creation for `MIGRATED` records; validation identical to a new admission.
- Confirmation endpoints writing append-only `academic_admission_verification_acts`, per-slot state,
  retained confirmer/time, distinct-actor rule, `VERIFIED`/`DISPUTED` computation, conflict refusal.
- Revocation endpoint: appends a `REVOKE` act, sets slot `REVOKED`, retains prior confirmation,
  moves the record to `REVOKED`.
- Pointer assignment on first verification; `ORIGINAL_ADMISSION_ORDER_CONFLICT` when a newly verified
  episode predates the pointer.
- Migration console UI: queue, candidate form, two independent panels, evidence fields, revoked and
  disputed states, no bulk confirm.
- Five-locale strings for trust states, slots, evidence types and revocation reasons.

**Acceptance criteria** (design §10 scenarios 59–71, 89; immigration cohort assertions 47–58 are
P6)

1. Management alone → `UNVERIFIED`, no pointer. Admin alone → `UNVERIFIED`, no pointer.
2. Both agreeing → `VERIFIED`, `verified_at` set, pointer set once.
3. Mismatched candidates → `DISPUTED`, no pointer, both acts and both candidate snapshots visible.
4. Same user filling both slots → 403 `CONFIRMATION_ACTOR_MUST_DIFFER` (or the recorded alternative,
   if `D1` is answered differently — the test asserts the recorded decision, not a hard-coded rule).
5. Revoke after verification → `REVOKED`; the confirming actor, timestamp, `verified_at` and every
   act remain queryable; pointer unchanged; audit entry written.
6. Re-confirm after revocation → `VERIFIED`; both revoke and confirm acts remain in order.
7. Revoke with blank reason → 422; Management revoking the Admin slot → 403.
8. No endpoint or trigger can clear the pointer; a raw `UPDATE … SET original_admission_id = NULL`
   fails.
9. A raw insert of a `MIGRATED` row with `verification_status='VERIFIED'` and no confirmations fails
   the CHECK.
10. New (`NEW_ADMISSION`) records never appear in the queue and are already `VERIFIED`.
11. Every confirmation and revocation writes one audit entry with slot, actor and candidate context.
12. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make build`,
    `make e2e` pass; Arabic RTL confirmation panels mirror correctly and show revoked state with both
    the last confirmation and the revocation.

**Rollback point:** `ADMISSION_MIGRATION_CONSOLE_ENABLED=false` and redeploy. Queue and confirmation
endpoints become unavailable (404/403 by route registration), the console is hidden, and all acts,
trust states and pointers stay in the database. Because verification is additive and never deletes,
re-enabling later resumes exactly where it stopped. Do not "roll back" by clearing confirmations.

**Risks / notes:** the pointer and the verification state can diverge if code writes them separately;
the acceptance tests must assert they are set in one transaction. A disputed record must never be
silently resolved by the last confirmer.

**Decisions needed:** `D1`, `D3`.

---

## 6. Phase 3 — Placement and earlier-intake authorization

**Objective:** placement becomes an explicit, authorized, historically complete act, and earlier-intake
placement is impossible without authorization.

**Completion condition:** same-intake and earlier-intake placements succeed with complete history, an
unauthorized earlier-intake placement is refused at both service and database level, and academic
records are byte-identical before and after.

**Entry criteria:** P1 exit gate; P2 exit gate if migrated students are to be placed.

**Work**

- Placement create/supersede endpoints, admission-status gate (`ADMITTED`/`ACTIVE` only),
  earlier-intake detection, authorizer from the session, mandatory reason, audit entries.
- Placement history endpoint and profile panel with original intake and placement intake separated.
- Earlier-intake banner with authorizer, reason and timestamp.
- Composite FK enforcement and the DB CHECK verified from the application path.
- Five-locale strings for the gate, the banner and the placement errors.

**Acceptance criteria** (design §10 scenarios 38–46, 82)

1. Placement into an earlier intake without a reason → 422; without
   `academic.authorize_placement` → 403; against a `PENDING` episode → 409.
2. Authorized placement stores original intake, placement intake, offering, authorizer, reason and
   timestamp. It writes the distinct audit actions `academic.placement.created`,
   `academic.placement.superseded` when a prior current placement is closed, and
   `academic.placement.earlier_intake_authorized` when the placement is earlier-intake. These
   actions commit atomically with the placement, prior-row closure and projection update; an audit
   failure rolls back all of them.
3. Raw SQL earlier-intake placement without authorizer/reason fails the CHECK; an offering from
   another intake fails the composite FK.
4. Placement never changes `admission_intake_id`, `admitted_program_id` or
   `admitted_program_offering_id`.
5. Supersession closes the prior row, keeps it queryable, and leaves exactly one current placement;
   concurrent supersession leaves one current row.
6. Enrolment, attendance, grade, assessment and timetable row counts and values are unchanged across
   the suite.
7. UI shows both intakes and the authorization details; all five locales render; Arabic mirrors the
   banner and table without fixed left/right spacing.
8. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make build`,
   `make e2e` pass.

**Rollback point:** set `ADMISSIONS_WRITE_ENABLED=false` (placement routes are gated with the
admission write surface) and redeploy. The legacy `PATCH /students/{id}/program-offering` remains
available until P8a, so operations continue; placements already written remain as history and are
still readable. No placement rows are deleted.

**Risks / notes:** the legacy offering endpoint writes `Student.program_offering_id` directly. During
P3 that is a known, temporary divergence; the P3 exit gate must record whether any such writes
occurred, because they are not placements and will not appear in placement history.

**Decisions needed:** none blocking.

---

## 7. Phase 4 — Programme-change workflow

**Objective:** programme changes are approved changes inside one episode, never new episodes, and the
original programme stays identifiable.

**Completion condition:** either role alone can approve a change that updates the current but not the
admitted programme, creates no episode, and a second episode in the same intake is refused; approved
history reconstructs without audit-log parsing.

**Entry criteria:** P3 exit gate (combined programme + offering changes use placement); `D2`
(self-approval) and `D8` (effective dating) have recorded positions.

**Work**

- Change-request endpoints for `PROGRAM_CHANGE` (with optional offering component),
  `PLACEMENT_CHANGE`, `EARLIER_INTAKE_PLACEMENT`, `WITHDRAWAL`, `STATUS_CORRECTION`.
- Single-approver review for ADMIN or MANAGEMENT; self-approval rule; atomic application of
  `current_program_id`, optional placement and projections; audit.
- One-pending-request-per-type enforcement and row locking on review.
- Episode timeline UI showing originally admitted programme, each approved change and the current
  programme; request form; no new-episode card.
- Self-service academic selection becomes a request rather than a direct write.
- Five-locale strings for change types, approval states and refusals.

**Acceptance criteria** (design §10 scenarios 27–37, 78–79, 81)

1. Management approves alone → `APPROVED`; Admin approves alone → `APPROVED`; no second-approver
   state exists in code, schema or UI.
2. Approval updates `current_program_id` (and placement, when the request carries an offering) and
   leaves `admitted_program_id` unchanged; no episode is created.
3. Two pending `PROGRAM_CHANGE` requests cannot coexist; concurrent review yields exactly one
   decision.
4. Self-approval is refused when `D2` says so; the test asserts the recorded decision.
5. Programme change on a `PENDING` future episode is allowed and leaves it `PENDING`.
6. Creating a second episode in the same intake with a different programme → 409
   `PROGRAM_CHANGE_NOT_NEW_ADMISSION`; after a terminal admission, a new episode for a different
   programme succeeds and prior history is intact.
7. Placement into an earlier intake creates no episode and no programme change.
8. Approved change history reconstructs admitted → change 1 → change 2 without reading audit logs.
9. Teacher/student review → 403; requester lacking permission cannot approve.
10. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make types`,
    `make build`, `make e2e` pass.

**Rollback point:** `ADMISSION_CHANGE_REQUESTS_ENABLED=false`. Request creation and review become
unavailable; already-approved changes stay applied because they are authoritative history; undecided
requests remain `PENDING` and visible read-only, to be decided when the phase is re-enabled. If
self-service must work during the window, the legacy direct-write path is restored by the same flag
and the divergence is logged for P8a.

**Risks / notes:** approving a change that carries an offering must apply programme and placement in
one transaction; a half-applied change is worse than a refused one.

**Decisions needed:** `D2`, `D8`.

---

## 8. Phase 5 — Intake date correction

**Objective:** official intake dates can be corrected by authorized users without silently moving
academic records or re-cohorting students.

**Completion condition:** a forward and a reverse correction leave every academic row untouched and
produce exactly one correction record and one audit entry each; every guarded refusal is exercised;
`PATCH` date edits are blocked once dependants exist.

**Entry criteria:** P0 exit gate; `D6` (authority on completed intakes) has a recorded position.

**Work**

- `POST /academic/periods/{id}/date-correction` with reason, authorization and all §4.2 validations.
- `academic_period_date_corrections` row and `academic.period.dates_corrected` audit entry.
- Placement reflagging via trigger; refusal when reflagging would create an unauthorized
  earlier-intake placement.
- `PATCH /academic/periods/{id}` refuses date changes once dependants exist
  (`USE_PERIOD_DATE_CORRECTION`).
- Academics page *Correct dates* dialog showing previous and new dates; both dates remain mandatory.
- Five-locale strings for the dialog and every refusal code.

**Acceptance criteria** (design §10 scenarios 6–12)

1. Correction without a reason → 422; without `academic.correct_period_dates` → 403; with an inverted
   range → 422.
2. Correction that would leave an attendance session, timetable-backed class, enrolment date or
   assessment due date outside the term → refused, and every academic row is unchanged.
3. Correction that would reorder intakes by `start_date` → refused.
4. Correction that would turn an unauthorized placement into an earlier-intake placement → refused;
   when authorization exists, it succeeds and the flag is recomputed.
5. Success writes exactly one correction row (old and new dates, actor, reason, counts) and one audit
   entry; `PATCH` date edits are refused once dependants exist.
6. No `admission_intake_id`, placement intake or pointer changes; no class, timetable, enrolment,
   grade or attendance row changes.
7. Reversal of a mistaken correction is performed by a new correction using the previous dates
   recorded in the correction row — the plan's own audited path.
8. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make build`,
   `make e2e` pass; the date dialog is usable in Arabic RTL and both dates are localized.

**Rollback point:** `ADMISSION_DATE_CORRECTION_ENABLED=false`. The endpoint and dialog disappear;
applied corrections remain, because they are recorded data changes with their own audit. A wrong
correction is reversed by another correction (the old dates are in the correction row), not by SQL
and not by a schema downgrade.

**Risks / notes:** the validation queries must run against the real tables, not a cached snapshot; a
correction validated against stale counts is exactly how a timetable slot ends up outside its term.

**Decisions needed:** `D6`.

---

## 9. Phase 6 — Immigration cohort switch

**Objective:** immigration and residence-permit operations use the original admission intake, with
trust made explicit rather than inferred.

**Completion condition:** named cohorts plus untrusted counts reconcile exactly to the active student
total; placement changes never move a cohort; flipping `ADMISSION_COHORT_SOURCE` back reproduces
pre-phase output on the same data.

**Entry criteria:** P2 exit gate (trust states and pointers exist); P1 exit gate; overview pagination
implemented; a reconciliation report showing named cohorts + untrusted = active students in scope.

**Work**

- Cohort joins through `students.original_admission_id` → `academic_admissions.admission_intake_id`.
- Trust-aware aggregation: named cohorts only for `VERIFIED`; one untrusted aggregate with reasons
  `UNVERIFIED`, `REVOKED`, `DISPUTED`, `NO_ADMISSION`.
- Overview columns for original intake and placement intake (labelled academic-placement-only);
  intake filter on the original intake; pagination.
- Student-level banner showing last confirmer, revocation or dispute; export trust column.
- Residence-permit and expiry roll-ups switched to the same basis.
- Five-locale strings, including Arabic and Russian plural categories for bucket counts.

**Acceptance criteria** (design §10 scenarios 47–58)

1. Backward placement (Spring 2026 admission → Autumn 2025 classes) keeps the Spring 2026 cohort;
   forward placement keeps it too.
2. Programme change does not move the cohort; a second admission after completion does not either.
3. The intake filter returns only students whose original admission intake matches.
4. `UNVERIFIED`, `REVOKED`, `DISPUTED` and `NO_ADMISSION` students appear only in the untrusted
   aggregate, with per-reason counts; no named cohort includes them.
5. A revoked student still displays the last confirmer and `verified_at` alongside the revocation.
6. Exports carry the trust column and an empty cohort for untrusted rows.
7. Cohort totals reconcile: sum(named cohorts) + untrusted counts = active students in scope, with no
   double counting.
8. No query path for cohort selection reads `academic_placements`; a code search and a test that
   removes placement rows still produce identical cohort output.
9. Overview paging is stable and does not load all active students per request.
10. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make build`,
    `make e2e` pass; Arabic and Russian plural forms are correct in the bucket labels.

**Rollback point:** `ADMISSION_COHORT_SOURCE=LEGACY` restores the previous cohort behaviour without
code revert and without touching data. No pointer, admission or verification row is modified by the
switch in either direction, so rollback is instantaneous and repeatable.

**Risks / notes:** this is the phase where a silent fallback is most dangerous. If the pointer is
missing, the code must bucket the student, not guess from placement or enrolment. The reconciliation
test is the exit gate, not a nice-to-have.

**Decisions needed:** none blocking (pointer correction is P7).

---

## 10. Phase 7 — Correction workflows

**Objective:** mistakes in terminal admissions and in the original pointer are corrected through
audited, privileged workflows that never erase history.

**Completion condition:** terminal-status and pointer corrections succeed with reason and permission,
fail without either, and leave every prior value and row queryable; no correction path deletes
history.

**Entry criteria:** P2 and P4 exit gates; `D4` (terminal correction authority) and `D5` (pointer
correction authority) have recorded positions.

**Work**

- Terminal status correction endpoint and dialog: target status, mandatory reason, status-history row
  with `is_correction = true`, prior `ended_at` preserved, §2.2 guards re-applied, audit.
- Original-pointer correction endpoint and dialog: ADMIN, mandatory reason, history row, transaction
  flag, trigger acceptance, audit.
- `STATUS_CORRECTION` change requests so Management can request rather than perform.
- Five-locale strings for both dialogs, reasons and refusals.

**Acceptance criteria** (design §10 scenarios 68–75)

1. Correcting `WITHDRAWN → ACTIVE` with no other active episode succeeds; history is append-only and
   the prior `ended_at` remains visible.
2. The same correction while another episode is `ACTIVE` → 409.
3. Missing reason → 422; missing permission → 403 (and Management can only request when `D4` says
   so).
4. Pointer correction by ADMIN with reason writes a history row and moves the pointer; non-ADMIN →
   403; missing reason → 422; raw SQL update without the flag fails.
5. Pointer correction cannot clear the pointer; the previous admission remains queryable in history.
6. No correction deletes a status-history row, verification act or audit entry.
7. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make build`,
   `make e2e` pass; the dialogs show previous values and require explicit confirmation.

**Rollback point:** `ADMISSION_CORRECTIONS_ENABLED=false`. Both correction surfaces disappear;
already-applied corrections remain as recorded history with their audit trail. A wrong correction is
itself corrected through the workflow once re-enabled — never by deleting rows.

**Risks / notes:** corrections are the one place where a privileged user can change an academic
outcome; the audit entry must carry the previous and new values, not just the new one.

**Decisions needed:** `D4`, `D5`.

---

## 11. Phase 8a — Retire direct placement writes

**Objective:** no client path can change academic placement outside an admission/placement/change
record.

**Completion condition:** every direct-write route returns the retirement code, placement still works
through its own endpoint, and no service outside the three allowed writers writes the projections;
rollback by flag restores the legacy routes on demand.

**Entry criteria:** P6 and P7 exit gates; at least one full intake cycle with no operational
dependence on the legacy endpoints (recorded, not assumed).

**Work**

- `PATCH /students/{id}` refuses `program_id`/`major_id` placement edits with
  `PLACEMENT_DIRECT_WRITE_RETIRED`.
- `PATCH /students/{id}/program-offering` retires; `POST /students/{id}/placements` is the only path.
- Self-service selection becomes a change request (already true when P4 is on).
- CSV import and onboarding stop writing projections directly.
- OpenAPI and generated types updated; frontend dialogs removed or redirected.
- Five-locale strings for the retirement errors.

**Acceptance criteria** (design §10 scenarios 76–79)

1. Direct placement writes on any student are refused with the stable code; the student's admission,
   placement and projections are unchanged.
2. Placement still works through the placement endpoint for same-intake and earlier-intake cases.
3. Student self-selection creates a pending request and changes nothing immediately.
4. Projections are updated only by the admission/placement/change services; a client payload cannot
   set them.
5. No remaining route or service writes `program_offering_id` outside those services (code search
   plus a test that asserts a single write path).
6. `make test-api`, `make lint-api`, `make typecheck`, `make lint-web`, `make i18n`, `make types`,
   `make build`, `make e2e` pass.

**Rollback point:** `ADMISSION_DIRECT_WRITE_MODE=ALLOW` restores the legacy endpoints by
configuration. Placements and episodes written meanwhile remain valid; the legacy path writes only
the projection, so re-enabling does not fabricate admission history.

**Risks / notes:** any operational script or integration that still calls the retired endpoints will
fail loudly by design; the phase should include a log review for 404/403 spikes in the first days.

**Decisions needed:** none blocking.

---

## 12. Phase 8b — Drop legacy projections

**Objective:** remove the compatibility columns once nothing reads them.

**Completion condition:** the application runs against a database without the three columns with
identical read behaviour, unchanged admission/placement/history counts, and a verified restore drill
recorded; this is the only phase whose completion consumes a backup.

**Entry criteria:** P8a stable through the agreed soak period; every active student is `VERIFIED` or
explicitly in the untrusted bucket with a recorded reason; no code path (including reports, exports,
CSV, API responses or SQL scripts) reads `Student.program_id`, `major_id` or `program_offering_id`;
`D9` answered with the removal window.

**Work**

- Drop the three projection columns and any index or FK that exists only for them.
- Remove projection fields from API schemas, OpenAPI and generated types.
- Remove the compatibility branches that read them.
- Update any documented operational query that referenced them.

**Acceptance criteria**

1. Code search shows no reads of the three columns outside historical migration files.
2. A full application smoke (`make smoke`) and `make e2e` pass against a database where the columns
   are absent.
3. Reports, immigration export, student profile, onboarding, placement and programme-change flows all
   work from episodes, placements and changes alone.
4. Pre-drop counts and checksums of admission, placement, change, act and history tables are
   identical after the drop (the drop touches nothing else).
5. The migration's downgrade either restores the columns empty (documented as non-restorative for
   values) or is explicitly marked irreversible; no claim of value restoration is made.
6. Backup taken immediately before, restore verification performed (`make backup`,
   `make verify-backup`), and the restore drill recorded.

**Rollback point:** **none in application terms.** Dropping columns is destructive; recovery is a
restore of the pre-drop backup, with the data written after the backup lost unless replayed. This is
why the phase is separate from P8a, requires a written go-ahead, a maintenance window and a verified
backup. Until that approval exists, the plan stops at P8a.

**Risks / notes:** projection columns are the last place where a stale writer could keep the old
model alive; the exit gate must include a log/code audit, not only passing tests.

**Decisions needed:** `D9`.

---

## 13. Decision gates

| ID | Decision | Default used by the plan | Blocks |
|---|---|---|---|
| D1 | May one account fill both migration slots? | No — distinct users enforced | P2 |
| D2 | May a requester approve their own programme change? | No — `SELF_APPROVAL_FORBIDDEN` | P4 |
| D3 | Acceptable historical evidence | `evidence_type` + reference + note, no upload | P2 |
| D4 | Who corrects a terminal admission? | ADMIN performs; MANAGEMENT requests | P7 |
| D5 | Who corrects the original pointer? | ADMIN only, reason + history row | P7 |
| D6 | Who corrects dates on a completed intake? | ADMIN only; either role while PLANNED/ACTIVE | P5 |
| D7 | May `ACTIVE` be set before the intake starts? | Yes, when no other episode is active | P1 |
| D8 | When does an approved programme change take effect? | Immediately on approval | P4 |
| D9 | When may legacy projections be dropped? | After two full intake cycles and full verification | P8b |

A default may be used to start a phase only if the institutional owner records it as accepted for
that phase. If a decision is still open at the phase's entry gate, the phase is either deferred or
scoped to the part that does not depend on it (for example, P2 can ship the queue and acts without
enforcing the distinct-actor rule, but then it cannot claim the exit gate).

---

## 14. Cross-phase verification and release gates

### 14.1 Commands

| Purpose | Command |
|---|---|
| Backend suite | `make test-api` |
| Backend lint | `make lint-api` |
| Frontend typecheck | `make typecheck` |
| Frontend lint | `make lint-web` |
| Translation parity | `make i18n` |
| Generated API types | `make types` |
| Frontend build | `make build` |
| Browser flows | `make e2e` |
| Development stack smoke | `make smoke` |
| Migration on dev | `make dev-migrate` |
| Backup / restore drill | `make backup`, `make verify-backup` |

`make test-api` and `make lint-api` are mandatory for every phase, including P0. UI-bearing phases
(P1–P8a) add `make typecheck`, `make lint-web`, `make i18n`, `make build`; browser-visible flows add
`make e2e`. No phase may pass by weakening an existing test: if an existing suite needs a new
expectation, the change is reviewed as part of the phase.

### 14.2 Invariants to check after every phase

Run as read-only SQL on the target environment and compare with expectations:

1. `SELECT student_id, count(*) FROM academic_admissions WHERE status='ACTIVE' GROUP BY 1 HAVING count(*) > 1` → zero rows.
2. No student has an `ADMITTED`/`ACTIVE` episode while another episode is `ACTIVE`.
3. Every live placement references an admission of the same student.
4. Every placement offering belongs to the placement intake.
5. Every `MIGRATED` `VERIFIED` admission has both confirmations and `verified_at`.
6. Every `students.original_admission_id` points to a `VERIFIED` admission, except records explicitly
   `REVOKED`/`DISPUTED` (which retain the pointer by design).
7. Every current placement count per student is 0 or 1.
8. Every admission status change has a matching status-history row (no orphan statuses after P1).
9. Admission, placement, change and act tables have no rows with `created_at` earlier than P0's
   deployment unless created by the verification workflow.
10. Untrusted immigration counts + named cohort counts reconcile to the active student total after P6.

### 14.3 Release rules

- Migrations are applied explicitly (`make dev-migrate`; production runs its own explicit migration
  procedure), never automatically on application start.
- A phase that adds a table may be deployed with its feature disabled; a phase that changes reads
  (P6) must be deployable in both directions via its switch.
- A failed acceptance criterion blocks the next phase; it is fixed in the same phase, not deferred.
- Every phase records: deployed revision, flag states, acceptance evidence (command output), and the
  known-issues list.

### 14.4 Synthetic test data

No phase may use institutional records. Fixtures are generated, deterministic and disposable:

- **Backend.** Pytest fixtures create students, periods, offerings and admissions with clearly
  synthetic identifiers (`TEST-PERIOD-2026S`, student numbers `TEST-ADM-00001`). Each test runs
  against the disposable `school_portal_test` database (`make dev-test-db`) inside a transaction that
  is rolled back, so no development volume is left changed.
- **Trust matrix fixture.** One synthetic student per state — verified, unverified, revoked,
  disputed, no pointer — plus one with an earlier-intake placement and one with a forward placement,
  so cohort tests never depend on migrated real data.
- **Lifecycle fixture.** An active episode with a prepared `PENDING` successor, a completed episode
  with a later admission, and a programme-change chain (admitted → change 1 → change 2).
- **E2E.** `make e2e` runs against its own disposable isolated stack with generated accounts. It must
  not point at development data, and never at the production-verification stack.
- **Volume and performance checks.** Generate 2,000 synthetic students in the test database for the
  immigration overview; never copy production rows.
- **Forbidden.** Production dumps, anonymised extracts, screenshots containing real names, seeding a
  shared environment to make a test pass, and `make restore` into anything but a scratch database.
- Cleanup is by discarding the test database or rolling back the transaction. No phase deletes rows
  from a shared environment to clean up after a test.

### 14.5 Regression and parity checks

- The pre-existing suites (`test_student_profile.py`, `test_student_program_offering.py`,
  `test_student_import.py`, `test_academic_period_scope.py`, `test_source_intakes.py`,
  `test_immigration.py`, `test_platform.py`, `test_authorization_scope.py`,
  `test_institutional_governance.py`) pass unchanged in every phase unless that phase's acceptance
  criteria state a deliberate behaviour change.
- For every phase that replaces a write path, the flag-off run must reproduce the pre-phase response
  and database effect for the same synthetic request. A diff in response shape or stored values is a
  defect, not an accepted variation.
- Academic and timetable reads are exercised after every phase that writes academic data: selected
  period retrieval, student timetable, class listing, attendance and grades views must return
  identical results for unchanged fixtures.
- `make i18n` is a gate, not a review note: a missing key in any of the five catalogs fails the
  phase.

---

## 15. Definition of done

The programme is complete when:

1. Every admission is an episode with a recorded intake, admitted programme and status history;
   future admissions are `PENDING` until the current programme ends.
2. Programme changes are approved changes inside an episode, with the original programme untouched
   and the change history complete.
3. Every migrated student has two independent confirmations, or is explicitly untrusted; no
   historical admission was inferred.
4. Revocation and dispute are visible states that preserve who confirmed what and when.
5. Placement into an earlier intake requires authorization and a reason, and no academic record was
   rewritten by it.
6. Immigration and residence-permit operations use the original admission intake for every verified
   student and bucket every other student explicitly.
7. Intake dates are mandatory, correctable only through the audited operation, and never moved
   underneath existing academic records.
8. Direct placement writes are gone; projections are gone or provably unused.
9. All five locales are complete, including Arabic RTL, and the full check suite passes at each
   phase's exit gate.

---

## 16. Approval gate

No phase starts until the institutional owner records:

1. acceptance of the design in `docs/scu-academic-admission-architecture.md` (Revision 3);
2. positions on D1–D9, even if the position is "use the default for the first phase";
3. confirmation that no admission data may be backfilled or inferred;
4. confirmation that the isolated production-verification environment is out of scope;
5. for P8b only, a separate written authorization for the destructive migration;
6. confirmation that the isolated production-verification environment is out of scope and will not
   be started, migrated or reseeded in any phase;
7. confirmation that no phase before P8b performs a destructive or irreversible operation.

This plan is planning-only: no code, migration, database, data or environment was changed to produce
it, and no test was run.
