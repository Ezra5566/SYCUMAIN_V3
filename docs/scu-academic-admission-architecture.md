# SCU — Stage 2: Academic Admission and Intake Architecture Design (Revision 3)

**Status:** Design only. No code, migration, schema change, data write or production action is
performed by this document.
**Supersedes:** Revision 2 of this document; Stage 2 design v1 (chat-only draft).
**Scope:** Admission episodes, intake (academic period) creation and date correction,
programme-change-versus-new-admission distinction, future admissions, earlier-intake placement,
immigration cohort basis, legacy-student verification, permissions, API/UI contracts, tests.
**Grounded in:** `apps/api/app/models/{academic,identity,audit,platform}.py`,
`apps/api/app/schemas/{academic,student}.py`,
`apps/api/app/services/{academic,student,immigration,document,student_import,source_intakes}.py`,
`apps/api/app/routers/{students,academic,immigration,documents}.py`,
`apps/api/app/permissions/constants.py`,
`apps/web/src/app/[locale]/(protected)/app/{students,academics}/**`,
`apps/web/messages/{en,zh,fr,ar,ru}.json`.

---

## 0. Confirmed institutional decisions applied

| # | Decision | Architectural consequence |
|---|---|---|
| 1 | Intake requires official start and end dates; neither Admin nor Management may create one without both | `academic_periods.start_date` / `end_date` mandatory at every write path; later date changes are a separate controlled operation (§4.2) |
| 2 | Either Admin or Management may independently approve a programme change; no second approver | `academic_admission_changes` keeps a single approval act; no quorum column, no second approval state |
| 3 | A future admission prepared while the current programme is active **is created as `PENDING`** and cannot activate until the current programme ends; one active programme at a time | `PENDING` is the only status a new episode may take while another episode is `ACTIVE`; enforced by service guard, trigger and partial unique index |
| 4 | A newly admitted student may be placed in an earlier intake's classes with explicit Admin/Management authorization and a recorded reason; original admission intake preserved separately from placement intake | Placement records both intakes plus authorizer/reason/timestamp; admission intake is never rewritten |
| 5 | Immigration and residence-permit operations always use the **original admission intake** as cohort basis | Set-once original-admission pointer with explicit trust state; cohort queries never read placement or latest episode |
| 6 | Management explicitly selects `ADMITTED` or `ACTIVE` at registration; lifecycle and activation constraints must be defined | Initial status is an explicit request field, constrained by decision 3 |
| 7 | Existing-student migration needs both Management and Admin confirmation per student, with who/when and audit history; no inference | Independent, append-only confirmation acts, slot state, verification trust state, no automatic backfill |

Superseded positions:

- Revision 2 allowed a future-intake episode to be `ADMITTED` while another was `ACTIVE`, and left
  the question open. Decision 3 as clarified is stricter: such an episode **must** be `PENDING`.
  §2.2 and §3.2 now enforce that, and revision 2's open decision 1 is closed.
- Revision 2 let a programme change be modelled either as a new episode or as a change. The
  approved distinction is now explicit: **change within the intake** versus **new episode after a
  completed/withdrawn admission** (§2.5, §3.4).
- Revision 2's "revoke returns the record to `UNVERIFIED` and clears the slot" erased historical
  confirmation. Revision 3 keeps every confirmation act, marks the slot `REVOKED`, and moves the
  record to an untrusted bucket instead (§5.4, §7.3).
- Revision 2 allowed intake date edits through the ordinary `PATCH`. Revision 3 routes any date
  change on an intake with dependants through a dedicated correction operation (§4.2).

---

## 1. Retained architecture (unchanged)

1. **`AcademicPeriod` is the operational intake.** Spring/Autumn cohorts are rows in
   `academic_periods` with `start_date` and `end_date` `NOT NULL`. No separate
   `admission_intakes` table.
2. **`ProgramOffering` is intake-specific programme availability**, keyed by
   `UNIQUE (academic_period_id, source_id)`, with a nullable canonical `program_id` because the
   source sometimes has no canonical parent programme. No duplicate configuration table.
3. **`AcademicAdmission` is the student's admission episode** — one row per admission event, never
   a mutable "current admission" field on `Student` alone.
4. **`AcademicAdmissionChange` is the request/approval/history mechanism** for changes after an
   admission exists, including programme changes inside the same episode.
5. **Teaching sections and timetable stay as they are**: `ClassSection` belongs to one
   `academic_period`, is linked to offerings through `ClassSectionProgramOffering`,
   `Enrollment`/`AttendanceRecord`/`Grade`/`TimetableEntry` remain the academic record. Admission
   and placement never rewrite them.
6. **Compatibility projections only where necessary**: `Student.program_id`,
   `Student.program_offering_id`, `Student.major_id` remain readable but become derived mirrors,
   written only by the admission/placement/programme-change services.
7. **Five languages** — English, Chinese, French, Arabic (RTL), Russian — for every new status,
   reason, banner and error code.
8. **Security, audit and integrity**: existing role/permission model, append-only `AuditLog`
   records, `ON DELETE RESTRICT` on academic references, and no destructive updates to academic
   history.

Not carried forward: duplicate intake tables, any second-approver workflow, any "latest episode"
cohort rule, any silent revocation or silent backfill.

---

## 2. Admission lifecycle (deliverable 2)

### 2.1 States

`AcademicAdmissionStatus`:

| State | Meaning | Academic effect |
|---|---|---|
| `PENDING` | Admission prepared for an intake but not institutionally admitted; **the only state a new episode may take while another episode is `ACTIVE`** | None. No placement, no enrolment, no immigration cohort |
| `ADMITTED` | Admitted for the intake; a place is held, the episode is not yet in force. Permitted only when the student has **no** `ACTIVE` episode | Pre-term administration; placement permitted (decision 4); not the active programme |
| `ACTIVE` | The student's programme of study currently in force. At most one per student | Drives current programme, placement and student-facing academic surfaces |
| `COMPLETED` | Programme finished normally | Historical record; retained and readable |
| `WITHDRAWN` | Programme ended early by the student or institution | Historical record; retained and readable |
| `CANCELLED` | A prepared/confirmed admission that never became effective | Historical record; never reused as an admission of record |

Management's registration choice (decision 6) is therefore conditional, not free: `ACTIVE` and
`ADMITTED` are offered only when the student has no `ACTIVE` episode; otherwise the form offers
`PENDING` and explains why.

### 2.2 Transition table

| From | To | Allowed | Guard |
|---|---|---|---|
| — | `PENDING` | yes | intake exists with both dates; offering belongs to that intake; no other live episode for the same `(student, intake)`; if the intake starts before the student's `ACTIVE` episode intake → refused (`ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE`) |
| — | `ADMITTED` | yes | as above **and the student has no `ACTIVE` episode**; otherwise 409 `ADMISSION_MUST_BE_PENDING` |
| — | `ACTIVE` | yes | as above **and the student has no `ACTIVE` episode**; sets `activated_at` |
| `PENDING` | `ADMITTED` | yes | **no `ACTIVE` episode exists**; the intake's dates and offering are unchanged |
| `PENDING` | `ACTIVE` | yes | **no `ACTIVE` episode exists**; sets `activated_at` |
| `PENDING` | `CANCELLED` | yes | reason required; `ended_at` set |
| `ADMITTED` | `ACTIVE` | yes | **no `ACTIVE` episode exists**; sets `activated_at` |
| `ADMITTED` | `CANCELLED` | yes | reason required; `ended_at` set |
| `ACTIVE` | `COMPLETED` | yes | `ended_at` set; terminal |
| `ACTIVE` | `WITHDRAWN` | yes | reason required; `ended_at` set; terminal |
| any | intake substitution (`admission_intake_id`) | **no** | immutable; a different intake is a different episode, or a placement (§6) |
| live episode (`PENDING`/`ADMITTED`/`ACTIVE`) | programme substitution (`current_program_id`) | only via change | `AcademicAdmissionChange` of type `PROGRAM_CHANGE` (§2.5); never a status transition |
| `COMPLETED` / `WITHDRAWN` / `CANCELLED` | any | **no** | terminal; only the privileged correction workflow of §5.5 |
| any verified episode | intake/offering rewrite | **no** | immutable; a genuine re-admission is a new episode |

Rules that make decision 3 literal:

- While episode A is `ACTIVE`, creating episode B is allowed **only** as `PENDING`. Requests for
  `ADMITTED` or `ACTIVE` are refused with `ADMISSION_MUST_BE_PENDING`, and the refusal names the
  blocking episode.
- `PENDING → ADMITTED` is likewise refused while any episode is `ACTIVE`. A prepared admission
  therefore cannot become "admitted" by a side door before the current programme ends.
- Activation refuses when the current `ACTIVE` episode has `ended_at IS NULL`. It never
  auto-completes the earlier programme: ending a programme is an explicit act (`COMPLETED` or
  `WITHDRAWN`) so that the reason and timestamp are real.
- Preparing a future admission never touches the `ACTIVE` episode, `Student` projections, class
  enrolment, timetable, attendance or grades.
- A new episode whose intake begins before the current `ACTIVE` episode's intake is not a "future
  admission"; it is a historical admission and belongs in the verified-migration workflow, not in
  ordinary admission creation. This prevents using admission creation to re-cohort a student.
- `CANCELLED` exists so an abandoned prepared admission cannot be mistaken for an admission of
  record.

### 2.3 One active programme, stated as invariants

1. `COUNT(*) WHERE student_id = ? AND status = 'ACTIVE'` is 0 or 1, always. Enforced by a partial
   unique index (§3.2) and a trigger, not only by service code.
2. No episode may enter `ADMITTED` or `ACTIVE` while another episode is `ACTIVE`. The unique index
   covers `ACTIVE`–`ACTIVE`; a trigger covers `ADMITTED`–`ACTIVE`.
3. Historical episodes are never deleted or overwritten. `DELETE` is forbidden by trigger; a
   mistaken episode is cancelled/withdrawn with a reason, and a mistaken end is corrected only
   through §5.5.
4. `Student.status` (account/enrolment status) is independent of `AcademicAdmissionStatus.ACTIVE`.
   The UI must not conflate them; labels differ in all five locales.

### 2.4 Initial registration (decision 6)

`POST /students/{id}/admissions` takes `initial_status ∈ {PENDING, ADMITTED, ACTIVE}` and
`initial_status` is stored verbatim for audit even if later transitions occur. Validation order:

1. intake must exist with both dates; offering must belong to it;
2. no other live episode for the same `(student, intake)`;
3. if the student has an `ACTIVE` episode: only `PENDING` is accepted;
4. `ACTIVE` sets `activated_at`; the episode is recorded with `record_origin = 'NEW_ADMISSION'`,
   `verification_status = 'VERIFIED'` and `verified_at = created_at`, because a new admission is
   authoritative and needs no historical confirmation; when it is the student's first episode the
   original-admission pointer is set in the same transaction (§5.2 step 6);
5. every accepted transition appends a row to `academic_admission_status_history`.

### 2.5 Programme change versus subsequent admission (deliverable 2, explicit distinction)

| Situation | Modelled as | Why |
|---|---|---|
| Student changes programme/major **within the existing admission intake** (any live state) | `AcademicAdmissionChange` of type `PROGRAM_CHANGE` on the **same** episode; approved by Admin **or** Management (decision 2) | The admission event did not change, only the programme of study |
| Originally admitted programme must stay identifiable | `academic_admissions.admitted_program_id` / `admitted_program_offering_id` are immutable; `current_program_id` carries the effective programme | History of the admission is not overwritten by a later change |
| Approved change must be preserved | Append-only `academic_admission_changes` row plus `academic_admission_status_history` entry when status also moves | Auditable sequence of approved changes |
| Student starts a **different programme after** the previous admission is `COMPLETED`/`WITHDRAWN` | **New** admission episode in the new intake, with its own `admitted_program_id` | A new admission event; the old episode remains intact |
| Student is placed into an **earlier intake's** classes | Placement only; **no** new episode, no change to `admission_intake_id` | Placement is academic delivery, not admission (decision 4) |
| Student changes programme and the new programme requires a different offering **in the same intake** | One `PROGRAM_CHANGE` request carrying `to_program_id` and optional `to_program_offering_id`; applies programme and placement in one transaction | Avoids two half-applied changes |
| Student wants a different programme while an episode is `PENDING` for a later intake | `PROGRAM_CHANGE` on that `PENDING` episode | The prepared admission is not yet an admission of record |

A programme change **never** creates an episode. A new episode is created only when there is no
live episode for the target intake and the previous admission is terminal — or when a first
admission is recorded for a student who has none.

---

## 3. Database relationship and constraint design (deliverable 3)

### 3.1 New and changed tables

**`academic_admissions`** (new)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `student_id` | UUID FK `students.id` `ON DELETE RESTRICT` | indexed |
| `admission_intake_id` | UUID FK `academic_periods.id` `RESTRICT` | **intake of admission**; immutable once verified or once `ACTIVE` was ever reached |
| `admitted_program_id` | UUID FK `programs.id` nullable | **originally admitted programme**; immutable after creation |
| `admitted_program_offering_id` | UUID FK `program_offerings.id` `RESTRICT` | admission-time offering; immutable |
| `current_program_id` | UUID FK `programs.id` nullable | effective programme; changed only through an approved `PROGRAM_CHANGE` |
| `current_program_changed_at` | timestamptz nullable | |
| `status` | varchar(20) | `AcademicAdmissionStatus` |
| `initial_status` | varchar(20) | audit-only record of Management's registration choice |
| `record_origin` | varchar(20) | `NEW_ADMISSION` / `MIGRATED`; decides whether dual confirmation is required |
| `verification_status` | varchar(20) | `UNVERIFIED` / `VERIFIED` / `DISPUTED` / `REVOKED`; a `NEW_ADMISSION` is authoritative and `VERIFIED` from creation |
| `management_confirmation_state` | varchar(20) | `NONE` / `CONFIRMED` / `REVOKED` |
| `management_confirmed_by_id` / `management_confirmed_at` | UUID FK `users.id` / timestamptz | last confirming act, **retained after revocation** |
| `management_revoked_by_id` / `management_revoked_at` / `management_revocation_reason` | | revocation act, retained |
| `admin_confirmation_state`, `admin_confirmed_*`, `admin_revoked_*` | | same shape for the Admin slot |
| `verified_at` | timestamptz nullable | last time both slots became `VERIFIED`; for `NEW_ADMISSION` it is the creation timestamp |
| `activated_at` | timestamptz nullable | first transition into `ACTIVE` |
| `ended_at` | timestamptz nullable | set on `COMPLETED`/`WITHDRAWN`/`CANCELLED` |
| `end_reason` | text nullable | required for `WITHDRAWN`/`CANCELLED` |
| `created_by_id` | UUID FK `users.id` `RESTRICT` | who recorded the episode |
| `created_at` / `updated_at` | timestamptz | |

**`academic_admission_status_history`** (new, append-only)

`id`, `admission_id` FK `RESTRICT`, `from_status` nullable, `to_status`, `actor_id` FK `RESTRICT`,
`reason` nullable, `is_correction` boolean, `corrected_from_recorded_at` nullable, `created_at`.
One row per accepted transition, including every privileged correction. This is the queryable
lifecycle record; no status change is legitimate without a row here.

**`academic_placements`** (new — decision 4)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `student_id` | UUID FK `students.id` `RESTRICT` | indexed |
| `admission_id` | UUID FK `academic_admissions.id` `RESTRICT` | episode the placement serves; original intake stays on the admission |
| `academic_period_id` | UUID FK `academic_periods.id` `RESTRICT` | **placement intake** |
| `program_offering_id` | UUID FK `program_offerings.id` `RESTRICT` | must belong to `academic_period_id` |
| `is_earlier_intake_placement` | boolean NOT NULL | derived at write from intake dates |
| `authorized_by_id` | UUID FK `users.id` nullable | required when `is_earlier_intake_placement` |
| `authorization_reason` | text nullable | required when `is_earlier_intake_placement` |
| `effective_from` | date NOT NULL | |
| `ended_at` | timestamptz nullable | supersession timestamp |
| `created_by_id` | UUID FK `users.id` `RESTRICT` | |
| `created_at` / `updated_at` | timestamptz | |

**`academic_admission_changes`** (new — request/approval/history)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `admission_id` | UUID FK `academic_admissions.id` `RESTRICT` | |
| `change_type` | varchar(40) | `PROGRAM_CHANGE`, `PLACEMENT_CHANGE`, `EARLIER_INTAKE_PLACEMENT`, `WITHDRAWAL`, `STATUS_CORRECTION` |
| `from_program_id` / `to_program_id` | UUID FK `programs.id` nullable | programme change pair; `to_` required for `PROGRAM_CHANGE` |
| `from_program_offering_id` / `to_program_offering_id` | UUID FK `program_offerings.id` nullable | optional placement component |
| `target_period_id` | UUID FK `academic_periods.id` nullable | placement intake, when the change moves placement |
| `proposed_data` / `current_data_snapshot` | jsonb | safe before/after, never secrets |
| `reason` | text | mandatory for `PLACEMENT_CHANGE`, `EARLIER_INTAKE_PLACEMENT`, `WITHDRAWAL` |
| `requested_by_id` / `requested_at` | UUID FK `users.id` `RESTRICT` / timestamptz | |
| `status` | varchar(20) | `PENDING` / `APPROVED` / `REJECTED` / `CANCELLED` |
| `reviewed_by_id` / `reviewed_at` | UUID FK `users.id` / timestamptz | **one** reviewer (decision 2) |
| `decision_reason` | text nullable | |

**`academic_admission_verification_acts`** (new, append-only — decision 7)

`id`, `admission_id` FK `RESTRICT`, `slot` (`MANAGEMENT`/`ADMIN`), `action`
(`CONFIRM`/`REVOKE`), `actor_id` FK `RESTRICT`, `acted_at`, `candidate_intake_id` FK,
`candidate_program_id` FK nullable, `evidence_type`
(`ADMISSION_LETTER`/`ENROLMENT_RECORD`/`REGISTER_EXTRACT`/`OTHER`), `evidence_reference` text,
`evidence_note` text, `revocation_reason` text, `resulting_verification_status`. Confirmation acts
are never deleted or updated.

**`academic_period_date_corrections`** (new — §4.2)

`id`, `academic_period_id` FK `RESTRICT`, `previous_start_date`, `previous_end_date`,
`new_start_date`, `new_end_date`, `reason` NOT NULL, `actor_id` FK `RESTRICT`, `created_at`,
`placements_reflagged` int, `admissions_rechecked` int.

**`student_original_admission_history`** (new — §5.4)

`id`, `student_id` FK `RESTRICT`, `previous_admission_id` nullable FK, `new_admission_id` FK,
`reason` NOT NULL, `actor_id` FK `RESTRICT`, `created_at`.

**Changed existing tables**

- `academic_periods`: add `CHECK (end_date >= start_date)`; both dates already `NOT NULL`.
- `program_offerings`: add `UNIQUE (academic_period_id, id)` so the composite FKs below are
  expressible.
- `students`: add `original_admission_id` UUID FK `academic_admissions.id` `RESTRICT`, nullable,
  unique; `program_id`, `program_offering_id`, `major_id` documented as projections. Optional
  `original_admission_locked_at` is **not** added — trust is read from the admission row.
- `immigration_profiles`: **no cohort column**. Cohort is derived from
  `students.original_admission_id → academic_admissions.admission_intake_id`. Denormalising it
  would create a second source of truth.

### 3.2 Constraints and indexes

```sql
-- Decision 3: at most one active programme per student.
CREATE UNIQUE INDEX uq_academic_admission_one_active
  ON academic_admissions (student_id)
  WHERE status = 'ACTIVE';

-- One live episode per student per intake; terminal history is unconstrained.
CREATE UNIQUE INDEX uq_academic_admission_student_intake_live
  ON academic_admissions (student_id, admission_intake_id)
  WHERE status IN ('PENDING', 'ADMITTED', 'ACTIVE');

-- Offering must belong to the stated intake (both admission and placement).
ALTER TABLE program_offerings
  ADD CONSTRAINT uq_program_offering_period_id UNIQUE (academic_period_id, id);
ALTER TABLE academic_admissions
  ADD CONSTRAINT fk_admission_offering_in_intake
  FOREIGN KEY (admission_intake_id, admitted_program_offering_id)
  REFERENCES program_offerings (academic_period_id, id);
ALTER TABLE academic_placements
  ADD CONSTRAINT fk_placement_offering_in_period
  FOREIGN KEY (academic_period_id, program_offering_id)
  REFERENCES program_offerings (academic_period_id, id);

-- Lifecycle coherence.
ALTER TABLE academic_admissions
  ADD CONSTRAINT ck_admission_active_has_activation
    CHECK (status <> 'ACTIVE' OR activated_at IS NOT NULL),
  ADD CONSTRAINT ck_admission_terminal_has_end
    CHECK ((status IN ('COMPLETED','WITHDRAWN','CANCELLED')) = (ended_at IS NOT NULL)),
  ADD CONSTRAINT ck_admission_end_reason
    CHECK (status NOT IN ('WITHDRAWN','CANCELLED') OR end_reason IS NOT NULL);

-- Verification state is never inferred from erased columns (§5.4).
ALTER TABLE academic_admissions
  ADD CONSTRAINT ck_mgmt_revoked_fields
    CHECK ((management_confirmation_state = 'REVOKED')
           = (management_revoked_at IS NOT NULL)),
  ADD CONSTRAINT ck_admin_revoked_fields
    CHECK ((admin_confirmation_state = 'REVOKED')
           = (admin_revoked_at IS NOT NULL)),
  ADD CONSTRAINT ck_mgmt_confirmed_has_actor
    CHECK (management_confirmation_state <> 'CONFIRMED'
           OR management_confirmed_at IS NOT NULL),
  ADD CONSTRAINT ck_admin_confirmed_has_actor
    CHECK (admin_confirmation_state <> 'CONFIRMED'
           OR admin_confirmed_at IS NOT NULL),
  ADD CONSTRAINT ck_record_origin
    CHECK (record_origin IN ('NEW_ADMISSION','MIGRATED')),
  ADD CONSTRAINT ck_verified_requires_both
    CHECK (verification_status <> 'VERIFIED'
           OR record_origin = 'NEW_ADMISSION'
           OR (management_confirmation_state = 'CONFIRMED'
               AND admin_confirmation_state = 'CONFIRMED')),
  ADD CONSTRAINT ck_origin_status
    CHECK (record_origin = 'MIGRATED'
           OR verification_status = 'VERIFIED'),
  ADD CONSTRAINT ck_revoked_requires_slot
    CHECK (verification_status <> 'REVOKED'
           OR management_confirmation_state = 'REVOKED'
           OR admin_confirmation_state = 'REVOKED');

-- Decision 4: earlier-intake placement is impossible without authorizer and reason.
ALTER TABLE academic_placements
  ADD CONSTRAINT ck_placement_earlier_authorized
  CHECK (NOT is_earlier_intake_placement
         OR (authorized_by_id IS NOT NULL AND authorization_reason IS NOT NULL)),
  ADD CONSTRAINT ck_placement_reason_not_blank
  CHECK (authorization_reason IS NULL OR length(btrim(authorization_reason)) > 0);

-- One current placement per student; superseded placements remain as history.
CREATE UNIQUE INDEX uq_academic_placement_current
  ON academic_placements (student_id)
  WHERE ended_at IS NULL;

-- One pending request of each type per admission: stops double approval races.
CREATE UNIQUE INDEX uq_admission_change_one_pending
  ON academic_admission_changes (admission_id, change_type)
  WHERE status = 'PENDING';

-- At most one original admission per student.
CREATE UNIQUE INDEX uq_student_original_admission
  ON students (original_admission_id)
  WHERE original_admission_id IS NOT NULL;

-- Cohort lookups.
CREATE INDEX ix_students_original_admission ON students (original_admission_id);
CREATE INDEX ix_admission_intake_status
  ON academic_admissions (admission_intake_id, status);
```

Additional table-level checks:

```sql
ALTER TABLE academic_admission_changes
  ADD CONSTRAINT ck_program_change_target
    CHECK (change_type <> 'PROGRAM_CHANGE'
           OR (to_program_id IS NOT NULL
               AND (from_program_id IS NULL OR to_program_id <> from_program_id))),
  ADD CONSTRAINT ck_change_review_pair
    CHECK ((status = 'APPROVED' OR status = 'REJECTED')
           = (reviewed_by_id IS NOT NULL AND reviewed_at IS NOT NULL)),
  ADD CONSTRAINT ck_no_self_approval
    CHECK (reviewed_by_id IS NULL OR reviewed_by_id <> requested_by_id);

ALTER TABLE academic_admission_status_history
  ADD CONSTRAINT ck_status_history_distinct
    CHECK (from_status IS NULL OR from_status <> to_status);
```

### 3.3 Triggers (each with a dedicated test)

1. `trg_admission_admitted_guard` — raises when a row enters `ADMITTED` or `ACTIVE` while another
   row for the same student is `ACTIVE`. Complements the unique index, which cannot express the
   `ADMITTED`–`ACTIVE` case.
2. `trg_admission_transition_guard` — rejects transitions outside §2.2 (including any transition out
   of a terminal state unless `is_correction` is set through the privileged path's transaction-local
   flag `scu.admission_correction`), and writes `academic_admission_status_history`.
3. `trg_admission_immutable` — rejects changes to `admission_intake_id`,
   `admitted_program_id`, `admitted_program_offering_id`, `initial_status` once
   `verification_status = 'VERIFIED'` or the row has ever been `ACTIVE`.
4. `trg_admission_no_delete` — rejects `DELETE` on `academic_admissions`,
   `academic_placements`, `academic_admission_changes`, `academic_admission_status_history`,
   `academic_admission_verification_acts`.
5. `trg_original_admission_once` — `students.original_admission_id` may be set when null; an update
   is accepted only when the transaction-local flag `scu.original_admission_correction` is `on`
   **and** a `student_original_admission_history` row for the student was inserted in the same
   transaction. Clearing to `NULL` is always rejected.
6. `trg_period_dates_recheck` — after a correction, recompute
   `academic_placements.is_earlier_intake_placement` for placements in that intake, refuse if any
   placement would become earlier-intake without authorizer/reason, and never touch enrolments,
   attendance, grades or timetable rows.
7. `trg_admission_change_review_guard` — rejects `APPROVED`/`REJECTED` transitions unless a
   reviewer is present, and prevents re-reviewing a decided request.

### 3.4 Programme, admission and placement relationships

- `academic_admissions.admitted_program_id` is the historical original programme. It is never
  updated by a programme change; `current_program_id` is.
- `academic_admission_changes` stores the approved programme changes, so the full sequence
  (admitted → change 1 → change 2) is reconstructible without touching the admission row.
- `Student.program_id` mirrors `current_program_id`; `Student.major_id` mirrors that programme's
  `major_id`; `Student.program_offering_id` mirrors the current placement's offering. All three are
  written only inside the admission/placement/change transactions.
- `academic_placements.admission_id` ties every placement to the episode it serves, so original
  intake, current placement intake and assigned offering are all available from one row plus its
  admission.

### 3.5 Original admission intake versus placement intake

- **Original admission intake** = `admission_intake_id` of the student's first verified admission,
  pointed at by `students.original_admission_id`. Written once by the verification workflow;
  replaceable only by the privileged correction of §5.4.
- **Placement intake** = `academic_placements.academic_period_id` of the row with
  `ended_at IS NULL`.
- The two may differ in either direction: later is normal progression, earlier is the authorized
  exception of decision 4. Neither writes the other.
- A programme change never changes either intake. A placement never creates an admission.

---

## 4. Intake creation and date correction (decision 1)

### 4.1 Creation

- `AcademicPeriodCreate` requires `start_date` and `end_date`, with `end_date >= start_date`.
  `AcademicPeriodUpdate` must validate the merged result and must not permit clearing either date.
- DB `CHECK (end_date >= start_date)` so no writer — API, importer, seed, script — can bypass it.
- Every path is in scope: `services/source_intakes.py`, staged importer
  `services/academic_import.py` period rows, `seed_academic.py`, any onboarding path that would
  implicitly create a period. A source row without both dates is a row-level error, never silently
  dated.
- Intakes are selected, never typed, wherever an admission or placement references one; the picker
  shows `name` plus the date range.
- No permission lets Admin *or* Management create a dateless intake: enforced in schema, DB and
  tests, not in a UI hint.

### 4.2 Controlled date correction

Official dates remain mandatory; correcting them is a distinct, authorized operation rather than an
edit.

**Route:** `POST /academic/periods/{id}/date-correction`
**Permission:** `academic.correct_period_dates` (ADMIN and MANAGEMENT). Corrections on an intake
already `COMPLETED` require ADMIN (recommended default; §11.6).
**Body:** `new_start_date`, `new_end_date`, `reason` (mandatory, non-blank, min 20 characters),
optional `evidence_reference`.

**Validation, all before any write, inside one transaction that locks the period row:**

1. Both dates present and `new_end_date >= new_start_date`.
2. **Ordering preserved.** Sorting all intakes by `start_date` must produce the same sequence before
   and after. A correction may move an intake within its own slot in the sequence but may not move
   it past a neighbour; this stops a correction from silently re-cohorting students or reordering
   "Earlier intake" placement decisions.
3. **Academic records stay inside the term.** No `class_sections`, `timetable_entries`,
   `enrollments` (`enrolled_at`/`dropped_at` dates), `attendance_records.session_date`, or
   `assessments.due_date` associated with that intake may fall outside the corrected range. If any
   would, the correction is refused (`PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD`) and the records
   are left untouched. Corrections never shift classes, timetable slots, enrolment dates or results.
4. **Admissions.** Every admission whose `admission_intake_id` is this intake is rechecked; the
   correction may not move the intake before the student's preceding verified admission intake
   (`PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY`).
5. **Placements.** Recompute `is_earlier_intake_placement` for all placements in the intake. If a
   placement would become earlier-intake without authorizer and reason, the correction is refused
   (`PERIOD_CORRECTION_REQUIRES_PLACEMENT_AUTHORIZATION`). If a placement stops being
   earlier-intake, its authorization data is retained, never stripped.
6. **Programme offerings** are linked by `academic_period_id` and need no date change; availability
   semantics are unaffected.
7. **No admission intake, placement intake, `Student` projection or immigration cohort pointer is
   ever rewritten by a date correction.** A correction changes the dates of the term only.

**Effects:** insert one `academic_period_date_corrections` row (previous and new dates, reason,
actor, counts), append `audit_logs` entry `academic.period.dates_corrected` with the same context,
update the period, reflag placements. The ordinary `PATCH /academic/periods/{id}` refuses to change
dates when the intake has any offering, admission, placement, class section or timetable entry
(`USE_PERIOD_DATE_CORRECTION`); before dependants exist, normal editing is allowed.

---

## 5. Migration, verification and corrections (deliverables 4, 5)

### 5.1 Principles

- **Scope.** This workflow applies only to `record_origin = 'MIGRATED'` records. Admissions created
  after go-live are `NEW_ADMISSION`, authoritative from creation, and never enter the verification
  queue.
- **No automatic backfill.** No episode is created from `Enrollment`, `ClassSection.academic_period`,
  `Student.program_offering_id`, `created_at` or imported source data.
- Every pre-existing student starts with no admission and `original_admission_id = NULL`, shown as
  *Unverified*.
- An admission is historically verified only when both slots are `CONFIRMED` with matching
  candidate intake and programme.
- Unverified, revoked and disputed students are never silently dropped from reports; they appear in
  an explicit untrusted bucket (§7.3).

### 5.2 Workflow

1. **Queue.** `GET /students?admission_verification=UNVERIFIED` lists students with no verified
   admission, sortable by enrolment year, programme, student number.
2. **Proposal.** A Management or Admin user enters the candidate original intake, admitted
   programme and offering. Saving creates an `academic_admissions` row with
   `record_origin = 'MIGRATED'`, `verification_status = 'UNVERIFIED'`, both slot states `NONE`, or
   updates an existing unverified migrated candidate. The candidate is validated exactly like a new
   admission: offering belongs to the intake; no live duplicate.
3. **Independent confirmation.** `POST .../confirm/{slot}` writes one append-only row in
   `academic_admission_verification_acts` with slot, actor, timestamp, candidate snapshot and
   evidence, and updates only that slot's state/actor/timestamp on the admission. Re-confirming an
   already-`CONFIRMED` slot is refused (`SLOT_ALREADY_CONFIRMED`).
4. **Distinct actors (recommended default, §11.1).** The service refuses a confirmation when the
   acting user already filled the other slot (`CONFIRMATION_ACTOR_MUST_DIFFER`). This is a policy
   default, not a technical limit; relaxing it is one configuration decision.
5. **Verification.** When the second slot is confirmed, compare the two acts' candidate intake and
   programme. Agreement sets `verification_status = 'VERIFIED'` and `verified_at`; disagreement sets
   `DISPUTED` and writes an audit entry. A `DISPUTED` record never sets the original-admission
   pointer.
6. **Pointer assignment.** Set `students.original_admission_id` on the student's first episode when
   it is authoritative: at creation for `NEW_ADMISSION`, and on the first `VERIFIED` migrated
   admission for `MIGRATED`. If a previously verified admission already holds the pointer
   and the newly verified admission is chronologically *earlier*, do not move the pointer silently:
   raise `ORIGINAL_ADMISSION_ORDER_CONFLICT` and route to §5.4.
7. **Audit.** Append-only entries: `academic.admission.migration.candidate_saved`,
   `...management_confirmed`, `...admin_confirmed`, `...confirmation_revoked`, `...verified`,
   `...disputed`, `...pointer_set`, `...pointer_corrected` with `entity_type =
   'academic_admission'`/`'student'`, `entity_id`, and context
   `{student_id, intake_id, program_id, slot, evidence_type}`. The acts table remains the
   authoritative who/when; the audit log is the security record.
8. **Bulk safety.** CSV import may *stage* candidate intakes; staging never creates a verified
   admission, never sets the pointer, never counts as a confirmation. No bulk confirmation in v1.

### 5.3 Revocation without erasure

Revocation is an append-only act, not a column wipe:

- `POST .../confirm/{slot}/revoke` requires the slot's role permission and a non-blank reason. It
  appends a `REVOKE` act with actor, timestamp, reason and the candidate snapshot being revoked,
  sets that slot's state to `REVOKED` with revocation actor/time/reason, and **retains** the last
  `CONFIRMED` actor and timestamp.
- If the admission was `VERIFIED`, it becomes `REVOKED`. If it was `DISPUTED`, it stays `DISPUTED`
  with the revocation recorded. It never becomes "blank".
- `verified_at` is retained as "last verified at"; it is historical, not a current-state flag.
- Re-confirming after revocation appends a new `CONFIRM` act and can restore `VERIFIED` if both
  slots agree. The prior acts are still visible.
- A confirmation is never deleted, and no endpoint returns a record with the confirmer hidden.
- `DISPUTED` is used when the two acts' candidate snapshots disagree; revocation does not resolve a
  dispute by itself.

### 5.4 Original-admission pointer corrections

The pointer is set once by verification. It is deliberately *not* cleared on revocation, so a
revoked verification cannot silently rewrite immigration history. It can only be replaced through:

`POST /students/{id}/original-admission/correction` — permission
`academic.correct_original_admission` (ADMIN only; §11.5), body
`new_admission_id`, `reason` (mandatory), `evidence_reference`. In one transaction the service
inserts `student_original_admission_history` (previous and new admission, reason, actor), sets the
transaction-local flag `scu.original_admission_correction = on`, updates
`students.original_admission_id`, refreshes projections and audits
`academic.admission.pointer_corrected`. The trigger accepts the update only under that flag with a
matching history row. Clearing to `NULL` is impossible.

### 5.5 Correcting a mistaken terminal admission

`COMPLETED`/`WITHDRAWN`/`CANCELLED` are terminal for ordinary workflow. A mistake is fixed by:

`POST /students/{id}/admissions/{aid}/corrections/status` — permission
`academic.correct_admission_status` (ADMIN by default; Management may request through
`AcademicAdmissionChange` of type `STATUS_CORRECTION`), body `target_status`, `reason` (mandatory).

- Allowed targets: `PENDING`, `ADMITTED`, `ACTIVE`, `COMPLETED`, `WITHDRAWN`, `CANCELLED`, subject
  to §2.2 guards (so a correction cannot create two active episodes).
- The service appends `academic_admission_status_history` with `is_correction = true`,
  `from_status`, `to_status`, `reason`, actor and `corrected_from_recorded_at` (the previously
  recorded `ended_at`), keeps the original `ended_at`/`end_reason` visible in that history row, and
  sets the new status. Nothing is deleted.
- Reactivating an episode sets a new `activated_at` only if it was null; the original activation is
  preserved in history.
- Audit action `academic.admission.status_corrected`.
- This workflow never touches enrolments, attendance, grades, timetable or documents.

### 5.6 Rollout sequencing (design, not performed)

1. Add tables, columns, indexes, triggers, permissions; nothing reads them yet.
2. Ship read-only admission history and the verification queue; unverified students are labelled;
   existing screens keep working from projections.
3. Enable dual confirmation with acts and trust states.
4. Enable placement with the earlier-intake authorization gate.
5. Enable programme-change requests and single-approver review.
6. Add intake date correction; route `PATCH` date edits to it once dependants exist.
7. Switch immigration cohort reads to the original pointer with trust buckets.
8. Retire direct placement writes, then the legacy projections (§11.9).

Steps 3–4 are prerequisites for step 7; step 5 depends on episode storage from step 1; step 6
depends only on step 1.

---

## 6. Placement authorization (decision 4)

### 6.1 What is recorded

Each placement row records: original admission intake (via `admission_id`), placement intake,
assigned programme offering, authorizing administrator/manager, reason, effective date, creating
user, creation timestamp and supersession timestamp. Each write also appends
`academic.placement.created` / `academic.placement.superseded` /
`academic.placement.earlier_intake_authorized` to `audit_logs`, and, when it came from a change
request, the approved `academic_admission_changes` row.

### 6.2 Authorization gate

- `is_earlier_intake_placement = (placement_period.start_date < admission_intake.start_date)`.
- If true: require `academic.authorize_placement` (ADMIN or MANAGEMENT), require a non-blank reason
  of meaningful length, and store `authorized_by_id` from the authenticated caller — never from the
  request body.
- If false: no reason required; a first placement may proceed under `academic.manage_placements`.
- The gate is enforced in the service **and** by the DB CHECK, so imports cannot create an
  unauthorized cross-intake placement.
- Placement requires the episode to be `ADMITTED` or `ACTIVE`; a `PENDING` episode is refused
  (`PLACEMENT_REQUIRES_ADMITTED_EPISODE`). This keeps "prepared" admissions genuinely inert.
- Superseding closes the old row (`ended_at`, audited) and inserts a new one. Rows are never updated
  in place, so the full placement history is answerable.

### 6.3 What placement must not do

- It never modifies `academic_admissions.admission_intake_id`, `admitted_program_id` or
  `admitted_program_offering_id`.
- It never rewrites, moves or deletes `enrollments`, `attendance_records`, `grades`,
  `timetable_entries`, `assessments` or `academic_change_history`.
- It never changes past `Enrollment.status`.
- It never creates a new admission episode (decision 4's explicit rule).
- It does not implicitly enrol the student in the new intake's sections; enrolment stays a separate
  act with its own permissions and capacity checks.

### 6.4 Direct-write removal

| Path | Current behaviour | Target |
|---|---|---|
| `PATCH /students/{id}` with `program_id` / `major_id` | edits `Student` directly | refused with `PLACEMENT_DIRECT_WRITE_RETIRED`, pointing at the admission/change endpoints |
| `POST /students/me/academic` (`StudentAcademicUpdate`) | student self-selects programme/offering once | becomes a *request*: pending `AcademicAdmissionChange`, no direct write |
| `PATCH /students/{id}/program-offering` (`StudentProgramOfferingUpdate`) | direct offering reassignment with optional reason | replaced by `POST /students/{id}/placements` (single-intake) or `POST /students/{id}/placements` with authorization (earlier intake) |
| Onboarding with `program_offering_id` | writes projection only | creates admission + first placement in one transaction |

Until removal, these endpoints must refuse placement changes for a student with a verified original
admission, so history cannot be rewritten during the transition.

---

## 7. Immigration scope (decision 5)

### 7.1 Cohort basis

Cohort basis for every immigration and residence-permit operation is
`students.original_admission_id → academic_admissions.admission_intake_id`. Not
`academic_placements.academic_period_id`, not the current offering, not the latest admission, not
a programme-change target.

### 7.2 Rules

- An earlier-intake placement does not move a student into an earlier immigration cohort; a later
  placement does not move them forward.
- A subsequent admission (after completion) does not change the cohort.
- A programme change does not change the cohort.
- A date correction changes the intake's own dates but not which intake is the cohort; reports use
  the corrected dates.
- Residence-permit renewal lists, cohort counts, expiry roll-ups and document checklists all join
  the original admission intake.

### 7.3 Trust states in immigration queries (deliberate, not silent)

The admission referenced by `students.original_admission_id` carries `verification_status`. Queries
branch on it explicitly:

| `verification_status` | Live cohort aggregate | Student-level view | Export |
|---|---|---|---|
| `VERIFIED` | Included in its original intake cohort | Normal | Cohort column filled |
| `UNVERIFIED` | Excluded; counted in `UNTRUSTED` bucket, reason `UNVERIFIED` | Warning banner + verification link | Cohort column empty, trust column `UNVERIFIED` |
| `REVOKED` | Excluded; `UNTRUSTED` bucket, reason `REVOKED` | Banner shows last confirmed by/at, revoked by/at and reason; link to the admission | Trust `REVOKED`, last-confirmed fields included |
| `DISPUTED` | Excluded; `UNTRUSTED` bucket, reason `DISPUTED` | Banner shows both confirmations and the conflict; link to resolve | Trust `DISPUTED` |
| No pointer | `UNTRUSTED` bucket, reason `NO_ADMISSION` | Prompt to start verification | Trust `NO_ADMISSION` |

- A `NEW_ADMISSION` episode is authoritative and therefore always `VERIFIED`; it appears in its
  cohort immediately and never in the untrusted bucket.
- The untrusted bucket is one aggregate with per-reason counts, never folded into a named cohort.
- Revocation does not clear `verified_at`, the confirmer or the confirmation act; the banner can
  show exactly who confirmed what and when, and who revoked it and why.
- Historical reports already produced are not recomputed; live views reflect current trust. The
  audit trail records each change, so a past figure is explicable.
- The API response always carries `original_admission_intake_id`, `..._name`, `..._start_date`,
  `verification_status`, `last_verified_at` and `placement_intake_id`/`_name` labelled
  academic-placement-only.
- `immigration.view_all` still gates the overview; cohort basis is a service invariant, not a role
  capability. Documents stay student-scoped; no episode link is required, and if attribution is
  later needed it is an additive nullable column.

---

## 8. Role and permission matrix (deliverable 5)

New permissions (existing `academic.manage_periods` stays):

| Codename | Purpose |
|---|---|
| `academic.view_admissions` | read episodes, placements, change requests, verification acts |
| `academic.manage_admissions` | create `PENDING`/`ADMITTED`/`ACTIVE` per §2.2; edit an unverified candidate |
| `academic.activate_admission` | transition an episode to `ACTIVE` |
| `academic.end_admission` | `COMPLETED` / `WITHDRAWN` with reason |
| `academic.manage_placements` | create/supersede a same-or-later-intake placement |
| `academic.authorize_placement` | authorize an earlier-intake placement (reason mandatory) |
| `academic.approve_admission_change` | approve/reject one change request — single approver |
| `academic.confirm_admission_management` | fill the Management verification slot |
| `academic.confirm_admission_admin` | fill the Admin slot |
| `academic.correct_period_dates` | controlled intake date correction |
| `academic.correct_admission_status` | privileged correction of a terminal admission |
| `academic.correct_original_admission` | replace the original-admission pointer (ADMIN only) |

| Capability | ADMIN | MANAGEMENT | TEACHER | STUDENT |
|---|---|---|---|---|
| View admissions / placement | yes | yes | own classes only (`academic.view`; no cohort, reason or evidence fields) | own record only |
| Create intake (dates mandatory) | yes | yes | no | no |
| Correct intake dates | yes | yes (ADMIN only on a `COMPLETED` intake) | no | no |
| Create admission, choose `PENDING`/`ADMITTED`/`ACTIVE` | yes | **yes** (decision 6, constrained by decision 3) | no | no |
| Activate an admission | yes | yes | no | no |
| End an admission | yes | yes | no | no |
| Approve a programme change | **yes, alone** (decision 2) | **yes, alone** (decision 2) | no | no |
| Same/later-intake placement | yes | yes | no | no |
| Earlier-intake placement | yes + reason | yes + reason | no | no |
| Migration Management slot | no (wrong slot) | **yes** | no | no |
| Migration Admin slot | **yes** | no (wrong slot) | no | no |
| Revoke a confirmation | either slot | own slot only | no | no |
| Correct original-admission pointer | **yes** | no | no | no |
| Correct a terminal admission status | **yes** | request via change | no | no |
| Read immigration cohort by original intake | yes | yes | no | own only |

Notes:

- Decision 2 is encoded by giving both roles `academic.approve_admission_change`, with no quorum
  column and no second approval state.
- Verification permissions are slot-specific: broad academic permissions do not let a MANAGEMENT
  account fill the Admin slot.
- `student.edit` and `users.manage_students` confer no admission, placement or cohort authority.
- Teachers keep class-scoped access; they gain no admission, cohort, evidence or reason data.

---

## 9. API and UI implications (deliverable 6)

### 9.1 API

| Method & path | Purpose | Key rules |
|---|---|---|
| `POST /academic/periods` | create intake | both dates required; 422 when absent; `end_date >= start_date` |
| `PATCH /academic/periods/{id}` | edit intake | cannot clear dates; date change refused with `USE_PERIOD_DATE_CORRECTION` when dependants exist |
| `POST /academic/periods/{id}/date-correction` | controlled correction | reason + permission + §4.2 validation; writes correction row and audit |
| `GET /students/{id}/admissions` | episode history | status, admitted vs current programme, verification trust, last confirmed/revoked |
| `POST /students/{id}/admissions` | record an episode | `initial_status`; `ADMITTED`/`ACTIVE` refused with `ADMISSION_MUST_BE_PENDING` while one is active |
| `POST /students/{id}/admissions/{aid}/status` | transition | §2.2 table; reason for `WITHDRAWN`/`CANCELLED` |
| `POST /students/{id}/admissions/{aid}/corrections/status` | privileged correction | §5.5; reason; history entry |
| `GET /students/{id}/placements` | placement history | original and placement intake side by side |
| `POST /students/{id}/placements` | place student | episode must be `ADMITTED`/`ACTIVE`; earlier intake needs reason + permission |
| `POST /students/{id}/admissions/{aid}/changes` | request a change | `PROGRAM_CHANGE` applies to the same episode; one pending per type |
| `POST /academic/admission-changes/{id}/review` | approve/reject | single reviewer; self-approval refused; applies transactionally |
| `GET /students/{id}/admissions/{aid}/verification-acts` | confirmation history | full acts, including revoked, with evidence |
| `POST /students/{id}/admissions/{aid}/confirm/{slot}` | confirmation | slot-role match; distinct-actor default |
| `POST /students/{id}/admissions/{aid}/confirm/{slot}/revoke` | revocation | reason; appends act; never erases |
| `POST /students/{id}/original-admission/correction` | pointer correction | ADMIN; reason; history row required |
| `GET /immigration/?intake_id=…` | overview | filters on original admission intake; trust state and untrusted bucket |

Cross-cutting:

- Stable codes for every refusal: `ADMISSION_MUST_BE_PENDING`, `ADMISSION_ALREADY_ACTIVE`,
  `ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE`, `PROGRAM_CHANGE_NOT_NEW_ADMISSION`,
  `INTAKE_DATES_REQUIRED`, `USE_PERIOD_DATE_CORRECTION`,
  `PERIOD_DATES_CONFLICT_WITH_ACADEMIC_RECORD`,
  `PERIOD_CORRECTION_REQUIRES_PLACEMENT_AUTHORIZATION`,
  `PERIOD_CORRECTION_REORDERS_ADMISSION_HISTORY`, `EARLIER_INTAKE_REASON_REQUIRED`,
  `EARLIER_INTAKE_NOT_AUTHORIZED`, `PLACEMENT_REQUIRES_ADMITTED_EPISODE`,
  `VERIFICATION_CONFLICT`, `SLOT_ALREADY_CONFIRMED`, `CONFIRMATION_ACTOR_MUST_DIFFER`,
  `SELF_APPROVAL_FORBIDDEN`, `ORIGINAL_ADMISSION_ORDER_CONFLICT`,
  `PLACEMENT_DIRECT_WRITE_RETIRED`.
- 409 for lifecycle/approval conflicts, 422 for missing/invalid fields, 403 for role, slot or
  authorization violations.
- Concurrency: activation, review, verification, placement supersession and date correction each
  lock their row (`SELECT … FOR UPDATE`) and re-check invariants inside the transaction; the
  partial unique indexes are the final arbiter.
- `StudentDetail` gains read-only `original_admission_intake_*`, `current_admission_status`,
  `current_placement_intake_*`, `verification_status`; existing projections stay for compatibility.
- The immigration overview must gain pagination before cohort filtering is exposed to the whole
  student body (it currently loads all active students).

### 9.2 UI

- **Onboarding dialog**: intake select with dates, offering filtered to that intake, and an explicit
  **Initial admission status** choice. When the student already has an active programme, only
  `PENDING` is selectable, with the reason shown inline; `ADMITTED`/`ACTIVE` are disabled, not
  hidden without explanation.
- **Student profile**: *Admissions* panel listing each episode with **Originally admitted
  programme** and **Current programme** as separate immutable/labelled values, plus approved
  programme-change history; a prepared future admission is visibly "pending — will not activate
  until the current programme ends".
- **Placement panel**: original and placement intake as separate values, earlier-intake banner with
  authorizer, reason and timestamp.
- **Programme change**: request form inside the episode; single approve/reject for Admin or
  Management; no "awaiting second approval" state; approved changes appear in the episode timeline
  and never spawn a new episode row.
- **Migration console**: unverified queue; candidate entry; two independent confirmation panels with
  evidence type/reference, who and when; revoked state shows the last confirmation *and* the
  revocation, with a "re-confirm" action; disputed state shows both candidates; no "confirm all".
- **Corrections**: dedicated dialogs for intake date correction, terminal status correction and
  original-pointer correction, each requiring a reason and showing the prior values.
- **Immigration overview**: *Original admission intake* column and filter; placement intake labelled
  academic-placement-only; `Untrusted` bucket with per-reason counts (`Unverified`, `Revoked`,
  `Disputed`, `No admission`).
- **Academics page**: intake form requires both dates; the list shows date ranges and offers
  *Correct dates* rather than inline editing once dependants exist.

### 9.3 Five-language requirements

- New keys in `en`, `zh`, `fr`, `ar`, `ru` for: six admission statuses, four verification trust
  states, three slot states, the distinct-actor and pending-only explanations, programme-change
  history labels, evidence types, correction dialogs, all error codes and the untrusted bucket with
  per-reason labels.
- Arabic (RTL): logical properties (`ms-`/`me-`, `text-start`/`text-end`, `start-0`/`end-0`); no
  fixed left/right in the timeline, confirmation panels or correction dialogs. History tables must
  mirror column order but keep the date/number locale formatting; status indicators use icon +
  label, never colour alone, because mirrored layouts invert visual reading order. Reason and
  evidence fields accept Arabic text and are stored as UTF-8. Arabic plural categories are needed
  for the untrusted counts (`zero/one/two/few/many/other`), not a single `{count} students` string.
- Chinese: keep `name` and `name_zh` where supplied; no invented transliteration. Dates use the
  locale format, not the ISO string.
- Russian: plural forms for counts (`1 студент`, `2 студента`, `5 студентов`) in the untrusted
  bucket and cohort totals.
- French: accented programme names and reasons preserved; no ASCII folding in stored text.

---

## 10. Test scenarios (deliverable 7)

**Intake creation and correction (decision 1)**
1. Create without `start_date` → 422; without `end_date` → 422; both missing → 422.
2. `end_date < start_date` → 422; raw SQL insert with inverted dates → CHECK violation.
3. Update clearing a date → refused, value retained.
4. Staged/importer period row without dates → row error, no period created.
5. Admin and Management blocked identically (no role bypass).
6. `PATCH` dates on an intake with offerings/sections/admissions → 409 `USE_PERIOD_DATE_CORRECTION`.
7. Date correction without reason → 422; without permission → 403.
8. Correction that would put an existing `attendance_records.session_date` or
   `timetable_entries`-backed class outside the term → refused, records unchanged.
9. Correction that would reorder intakes by `start_date` → refused.
10. Correction that would make an unauthorized placement earlier-intake → refused; with
    authorization present, succeeds and reflags.
11. Correction writes one `academic_period_date_corrections` row and one audit entry with old and
    new dates.
12. Correction never alters `class_sections.academic_period_id`, timetable rows, enrolments, grades
    or admissions' intake ids.

**Future admissions (decisions 3, 6)**
13. Student with `ACTIVE` A: create B in a later intake as `PENDING` → succeeds, A untouched.
14. Same, requesting `ADMITTED` → 409 `ADMISSION_MUST_BE_PENDING`.
15. Same, requesting `ACTIVE` → 409 `ADMISSION_MUST_BE_PENDING`.
16. `PENDING → ADMITTED` while A is active → 409; B stays `PENDING`.
17. End A as `COMPLETED`, then `PENDING → ADMITTED → ACTIVE` → succeeds; exactly one active.
18. End A, then `PENDING → ACTIVE` directly → succeeds; history records both transitions.
19. Concurrent activation of B from two sessions → exactly one succeeds (index/trigger).
20. Raw SQL insert of a second `ACTIVE` row → unique index violation.
21. Raw SQL update of B to `ADMITTED` while A active → trigger violation.
22. Two live episodes in the same intake → refused by `uq_academic_admission_student_intake_live`.
23. Creating a `PENDING` episode in an intake earlier than the active episode's intake → 409
    `ADMISSION_INTAKE_PRECEDES_ACTIVE_EPISODE`.
24. Initial registration with `ACTIVE` and no active episode → succeeds, `activated_at` set.
25. Historical terminal episodes remain readable and unchanged after later admissions.
26. New admission alters no enrolment, attendance, grade or timetable row (row-level assertions).

**Programme change versus new admission (decision 2 and §2.5)**
27. `PROGRAM_CHANGE` approved by Management alone → `APPROVED`; `current_program_id` changes;
    `admitted_program_id` unchanged; **no new episode**.
28. Same request approved by Admin alone → identical outcome.
29. Before approval, `current_program_id` and `Student.program_id` are unchanged.
30. Two pending `PROGRAM_CHANGE` requests on one admission → second refused by the partial unique
    index.
31. Requester approving their own request → 403 `SELF_APPROVAL_FORBIDDEN`.
32. Teacher/student review → 403.
33. Programme change on a `PENDING` future episode → allowed, still `PENDING`.
34. Attempt to create a second episode in the same intake with a different programme → 409
    `PROGRAM_CHANGE_NOT_NEW_ADMISSION`.
35. After `COMPLETED`, creating a new episode for a different programme → succeeds; prior episode,
    its admitted programme and its change history intact.
36. Placement into an earlier intake creates **no** new episode.
37. Change history ordering (admitted → change 1 → change 2) is reconstructible from
    `academic_admission_changes` after several approvals.

**Earlier-intake placement (decision 4)**
38. Placement into an earlier intake without reason → 422.
39. Without `academic.authorize_placement` → 403.
40. Authorized placement → original intake, placement intake, offering, authorizer, reason,
    timestamp stored; audit entry written.
41. Raw SQL earlier-intake placement without authorizer/reason → CHECK violation.
42. Placement on a `PENDING` episode → 409 `PLACEMENT_REQUIRES_ADMITTED_EPISODE`.
43. Placement does not change `admission_intake_id` or `admitted_program_id`.
44. Supersession closes the old row and keeps it queryable; only one current placement per student.
45. Offering from a different intake than the placement intake → composite FK violation.
46. Placement leaves historical enrolment, attendance, grade and timetable rows untouched.

**Immigration cohort and trust (decisions 5, 7)**
47. Admitted Spring 2026, placed into Autumn 2025 classes → cohort is Spring 2026.
48. Admitted Spring 2026, placed forward into Autumn 2026 → cohort is Spring 2026.
49. Programme change does not change cohort.
50. Second admission after completion does not change cohort; pointer unchanged.
51. `intake_id` filter returns only students whose original admission intake matches.
52. Residence-permit and expiry roll-ups use the same cohort basis as the overview.
53. `UNVERIFIED` student → untrusted bucket with reason `UNVERIFIED`, absent from named cohorts.
54. `REVOKED` student → untrusted bucket with reason `REVOKED`; last confirmer and revocation are
    still returned; absent from named cohorts.
55. `DISPUTED` student → untrusted bucket with reason `DISPUTED`.
56. Student with no pointer → `NO_ADMISSION` bucket.
57. Untrusted counts are per reason and never folded into a cohort total.
58. Export carries the trust column and empty cohort for untrusted rows.

**Dual confirmation and revocation (decision 7)**
59. Management confirmation alone → `UNVERIFIED`; no pointer.
60. Admin confirmation alone → `UNVERIFIED`.
61. Both agreeing → `VERIFIED`, `verified_at`, pointer set once.
61a. A new (`NEW_ADMISSION`) student gets `VERIFIED` and the pointer without any confirmation act,
    and appears in the immigration cohort immediately.
61b. A `MIGRATED` record can never be `VERIFIED` without both slots (raw SQL CHECK violation).
62. Mismatched candidates → `DISPUTED`, no pointer, both acts visible.
63. Same user filling both slots → 403 `CONFIRMATION_ACTOR_MUST_DIFFER` (recommended default).
64. Re-confirming a filled slot → 409.
65. Revoke a slot after verification → status `REVOKED`; **acts and last confirmer retained**; the
    pointer is unchanged; immigration moves the student to the untrusted bucket.
66. Re-confirm after revocation → `VERIFIED` again; both the revoke and re-confirm acts remain.
67. Revoke with blank reason → 422; revoke the other role's slot as MANAGEMENT → 403.
68. `original_admission_id` cannot be updated or cleared by API or raw SQL outside the correction
    flag.
69. Pointer correction: ADMIN + reason writes a history row and moves the pointer; non-ADMIN → 403;
    missing reason → 422.
70. Newly verified admission earlier than the current pointer → `ORIGINAL_ADMISSION_ORDER_CONFLICT`,
    pointer unchanged until corrected.
71. Audit log contains one entry per confirmation/revocation with actor, timestamp and context.

**Terminal correction**
72. Correct `WITHDRAWN → ACTIVE` when no other active episode → succeeds, history row
    `is_correction = true`, prior `ended_at` retained in history.
73. Same correction when another episode is active → 409.
74. Correction without reason → 422; without permission → 403.
75. Correction never deletes or rewrites prior status-history rows.

**Direct-write retirement and projections**
76. `PATCH /students/{id}` with `program_id` on a verified student → `PLACEMENT_DIRECT_WRITE_RETIRED`.
77. `PATCH /students/{id}/program-offering` same case → refused, admission unchanged.
78. Student self-selection creates a pending change request, changing nothing immediately.
79. Approval updates `Student.program_id`/`major_id`/`program_offering_id` to match; client payloads
    cannot set them.

**RBAC, concurrency and audit**
80. Per-role endpoint matrix (403 vs 200) for every new route.
81. Concurrent review of one change request by two reviewers → exactly one `APPROVED`/`REJECTED`.
82. Concurrent placement supersession → one current placement remains.
83. Every mutation writes exactly one audit entry with the correct action code.

**Frontend / E2E**
84. Intake form cannot submit without both dates.
85. Onboarding disables `ADMITTED`/`ACTIVE` and explains when an active programme exists.
86. Prepared future admission renders as pending, not active, and cannot be activated in the UI.
87. Programme change appears in the episode timeline with no new episode card.
88. Earlier-intake placement asks for a reason and shows authorizer + reason afterwards.
89. Migration console shows revoked state with last confirmer *and* revocation; disputed state shows
    both candidates.
90. Date correction dialog requires a reason and displays previous dates.
91. Immigration overview shows original intake, support for untrusted reasons, and placement intake
    labelled separately.
92. All new strings render in en/zh/fr/ar/ru with no missing-key fallback; Arabic mirrors correctly;
    Russian and Arabic plural forms are correct; status indicators are not colour-only.

---

## 11. Remaining institutional decisions

Recommended defaults are stated; each still needs institutional confirmation before the related
work is considered final.

1. **Distinct migration confirmers.** Recommended default: the two slots must be filled by different
   users; the service enforces `CONFIRMATION_ACTOR_MUST_DIFFER`. *Confirm whether a single account
   holding both ADMIN and MANAGEMENT may act twice.*
2. **Self-approval.** Recommended default: the requester may not approve their own programme change
   (`SELF_APPROVAL_FORBIDDEN`), while decision 2's single-approver rule still holds. *Confirm.*
3. **Migration evidence standard.** Recommended default: record `evidence_type`
   (`ADMISSION_LETTER`, `ENROLMENT_RECORD`, `REGISTER_EXTRACT`, `OTHER`), a free-text reference and
   an optional note; no document upload required. *The accepted evidence itself is institutional.*
4. **Terminal-admission correction authority.** Recommended default: ADMIN only
   (`academic.correct_admission_status`), with Management limited to requesting a `STATUS_CORRECTION`
   change. *Confirm who may correct a mistakenly completed or withdrawn admission.*
5. **Original-pointer correction authority.** Recommended default: ADMIN only, mandatory reason and
   history row. *Confirm, and confirm who arbitrates when the two migration confirmations disagree.*
6. **Date-correction authority on completed intakes.** Recommended default: ADMIN only once the
   intake is `COMPLETED`; either role while `PLANNED`/`ACTIVE`. *Confirm.*
7. **Activation timing.** Recommended default: `ACTIVE` may be set before the intake's start date
   when no other episode is active (management judgement), with no date gate. *Confirm whether
   activation must wait for `start_date`.*
8. **Effective date of an approved programme change.** Recommended default: effective immediately on
   approval, with the change row timestamped; placements follow separately. *Confirm whether changes
   should instead take effect at the next intake boundary.*
9. **Legacy projection removal.** Recommended default: stop writing them when §6.4 lands, keep reads
   for two full intake cycles after every active student is verified, then drop them in a separate
   change. *Confirm the removal window.*

Closed by this revision: revision 2's question about `ADMITTED` for a future intake (now `PENDING`
only) and its question about programme change versus new episode (now §2.5).

---

## 12. Implementation sequence and dependencies

| Step | Work | Depends on | Reversible |
|---|---|---|---|
| 1 | Schema: admission, placement, change, status-history, verification-act, period-correction and pointer-history tables; FKs, indexes, CHECKs, triggers; new permissions seeded | — | Yes (tables unread) |
| 2 | Admission read APIs and profile history panel; verification queue (read-only) | 1 | Yes |
| 3 | Dual confirmation with acts, trust states, pointer assignment; migration console | 1, 2 | Yes (trust reads can revert to "unverified") |
| 4 | Placement service + earlier-intake authorization gate; retire direct placement writes behind refusal | 1 | Yes |
| 5 | Programme-change requests and single-approver review; `current_program_id` maintenance; episode timeline | 1, 4 | Yes |
| 6 | Intake date-correction endpoint and dialog; `PATCH` re-routing | 1 | Yes |
| 7 | Immigration cohort switch to pointer + trust buckets, pagination and filters | 3 | Yes until old reads are deleted |
| 8 | Terminal-admission and pointer correction workflows | 3, 5 | Yes |
| 9 | Remove deprecated projections and legacy cohort code | 7, 8, all students verified | **No** — requires explicit go-ahead |

Cross-cutting prerequisites: five-locale catalogs updated alongside steps 2–8; audit action codes
registered before each feature ships; no step may backfill admission data.

---

## 13. Changes in revision 3

1. `PENDING` is now the only status a new episode may take while another is `ACTIVE`; `ADMITTED`
   and `ACTIVE` are refused with `ADMISSION_MUST_BE_PENDING`, and `PENDING → ADMITTED` carries the
   same guard. Added `trg_admission_admitted_guard` because a unique index alone cannot express the
   `ADMITTED`–`ACTIVE` case. Closed revision 2's open decision 1.
2. Split original from effective programme: immutable `admitted_program_id` /
   `admitted_program_offering_id`, mutable `current_program_id`. Programme change is explicitly a
   same-episode change request; a new episode occurs only for a different programme after a
   terminal admission. Added programme-change columns, the one-pending-per-type index, self-approval
   and target checks, and the `PROGRAM_CHANGE_NOT_NEW_ADMISSION` refusal.
3. Replaced confirmation erasure with append-only
   `academic_admission_verification_acts`, per-slot `NONE`/`CONFIRMED`/`REVOKED` state, retained
   confirmer and `verified_at`, plus `DISPUTED`/`REVOKED` trust. Immigration now branches on trust
   with an explicit `UNTRUSTED` bucket instead of guessing a cohort.
4. Added the controlled intake date-correction operation, its correction table, permission,
   validation against academic records/admissions/placements, ordering preservation and the
   `trg_period_dates_recheck` behaviour. `PATCH` no longer edits dates with dependants.
5. Added `academic_admission_status_history`, the privileged terminal-admission correction, the
   original-pointer correction with `student_original_admission_history`, and governance defaults
   for distinct confirmers, self-approval, evidence, correction authority and projection removal.
6. Added `record_origin` so new admissions are authoritative and only migrated records need dual
   confirmation; pointer assignment now covers both origins without weakening the immigration rule.
7. Consistency sweep: explicit locks for activation, review, verification, placement and correction;
   missing FKs and uniqueness rules; no-delete and immutability triggers; role-slot revocation rules;
   trust-aware immigration reads; five-locale plural and RTL requirements; timetable/enrolment
   non-mutation guarantees.

---

## 14. Explicit non-actions

This review was design-only. No application source file, schema, migration, database, dataset,
Docker volume, browser session or production-verification environment was modified. No admission,
placement, intake, verification, correction or immigration record was created, updated or deleted.
No test was executed, because no behaviour changed. The only file written is this document.
