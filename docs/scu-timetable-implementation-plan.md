# SCU Timetable — Finalized Implementation Plan

**Status:** design; additive schema applied to the development database only; no academic data imported  
**Source:** `docs/scu-timetable-reference.json`  
**Source SHA-256:** `91a36ccea191b0e205f828e138eb5d4d3afe3b9a0ae2aa46b442decc0eeb95d4`  
**Record-level mapping:** `docs/scu-timetable-mapping-appendix.md`  
**Reconciliation evidence:** `docs/scu-timetable-reconciliation-report.md`, `docs/scu-timetable-reconciliation-diff.json`  
**Approval:** pending

---

## 1. Accepted decisions and boundaries

1. **2026 Autumn uses `block4`.** The source’s top-level `timeSlotFormats.block4.description` says “Used by 2026 Autumn”; all 23 Autumn rows use block labels and no single-period label. The conflicting per-semester `standard8` value is preserved as source metadata, not overwritten.
2. **No semester dates are invented.** `2025-autumn` and `2026-spring` cannot become `academic_periods` rows until SCU supplies start/end dates and an approved period code.
3. **No source program name is automatically mapped to a major or program.** Business Administration and Computer Science and Technology have proposed BBA/BCS links only. The other six program names remain unparented.
4. **Shared delivery is represented by one class section linked to multiple program offerings.** Nine shared session identities collapse into seven canonical sections; all pass the structural identity check and are listed individually in the appendix for final sign-off.
5. **The two N103 conflicts remain unresolved.** The four affected sessions and their two derived sections stay in staging as `HELD_N103_CONFLICT`; no live timetable entry is created and no two courses are merged.
6. **Official identifiers remain null where the source does not supply them.** Nullable `courses.code`, `class_sections.section_code` and `classrooms.capacity` are approved. Internal `ref:v1:` source keys are used only for provenance and are never labelled or displayed as official identifiers.
7. **Existing academic records are preserved.** The 24 enrollments, seven legacy courses, five legacy sections, six legacy timetable entries, five legacy classrooms and all academic-history rows are out of scope for deletion or rewrite.

### Additional constraint issues resolved as U3/U4

Two fields absent from the source are now approved as nullable:

- `courses.credits` is nullable. Source-missing credits are stored as `NULL`, never a default such as 3.
- `class_sections.capacity` is nullable. Source-missing capacities are stored as `NULL`, never a default such as 30.

Existing non-null legacy values are preserved. The migration and importer create no fabricated credits or capacities.

---

## 2. Final target schema

### 2.1 New reference and import tables

```text
timetable_formats
  code                 varchar(20) primary key
  name                 varchar(100) not null
  description          text
  source_description   text
  definition_json      jsonb not null
  created_at           timestamptz not null

timetable_slots
  id                   uuid primary key
  format_code          varchar(20) not null references timetable_formats(code)
  label                varchar(12) not null
  start_time           time not null
  end_time             time not null
  sort_order           integer not null
  unique (format_code, label)
  check (end_time > start_time)

academic_import_batches
  id                   uuid primary key
  source_name          varchar(200) not null
  source_sha256        char(64) not null
  status               varchar(20) not null  -- DRY_RUN | READY | APPLIED | FAILED | ROLLED_BACK
  dry_run              boolean not null default true
  counts_json          jsonb not null default '{}'
  created_by_id        uuid references users(id)
  created_at           timestamptz not null
  finished_at          timestamptz

academic_import_rows
  id                   uuid primary key
  batch_id             uuid not null references academic_import_batches(id)
  entity_type          varchar(30) not null
  source_key           varchar(160) not null
  source_locator       jsonb not null
  payload              jsonb not null
  action               varchar(20) not null  -- CREATE | SKIP | CONFLICT | HELD
  error_code           varchar(80)
  target_table         varchar(60)
  target_id            uuid
  created_at           timestamptz not null
  unique (batch_id, entity_type, source_key)

program_offerings
  id                   uuid primary key
  academic_period_id   uuid not null references academic_periods(id)
  program_id           uuid null references programs(id)
  source_id            varchar(80) not null
  source_key           varchar(160) not null unique
  name                 varchar(200) not null
  name_zh              varchar(200)
  import_batch_id      uuid null references academic_import_batches(id)
  created_at           timestamptz not null
  updated_at           timestamptz not null
  unique (academic_period_id, source_id)

class_section_program_offerings
  class_section_id     uuid not null references class_sections(id) on delete restrict
  program_offering_id  uuid not null references program_offerings(id) on delete restrict
  primary key (class_section_id, program_offering_id)
```

`program_offerings.program_id` deliberately remains nullable. It is the only place where a reviewed parent program may later be attached. The import creates no `majors` or `programs` rows.

### 2.2 Additions to existing academic tables

```text
academic_periods
  source_key                  varchar(160) unique
  name_zh                     varchar(200)
  source_timetable_format     varchar(20)     -- declared value, e.g. standard8 for 2026 Autumn
  timetable_format_code       varchar(20) references timetable_formats(code)
  timetable_format_note       text            -- stores the block4 resolution rationale
  import_batch_id             uuid references academic_import_batches(id)

courses
  code                        varchar(20) null  -- approved relaxation of NOT NULL
  name_zh                     varchar(200)
  source_key                  varchar(160) unique
  credits                     integer null      -- approved U3; NULL when source omits it
  import_batch_id             uuid references academic_import_batches(id)

classrooms
  campus                      varchar(100)
  capacity                    integer null      -- approved relaxation of NOT NULL
  source_key                  varchar(160) unique
  import_batch_id             uuid references academic_import_batches(id)

class_sections
  section_code                varchar(20) null  -- approved relaxation of NOT NULL
  source_label                varchar(300)      -- non-official descriptive label
  source_key                  varchar(160) unique
  capacity                    integer null      -- approved U4; NULL when source omits it
  import_batch_id             uuid references academic_import_batches(id)

timetable_entries
  slot_label                  varchar(12)       -- e.g. 5-8; exact source label
  source_key                  varchar(160) unique
  import_batch_id             uuid references academic_import_batches(id)
```

No changes to `enrollments`, `attendance_records`, `assessments`, `grades`, `academic_change_history`, `teacher_assignments`, `majors` or `programs`.

### 2.3 Index and constraint changes

- Unique `source_key` on every imported academic entity; this is the idempotency key.
- Unique `(academic_period_id, source_id)` on `program_offerings`.
- Index `program_offerings(academic_period_id)`.
- Index `class_section_program_offerings(program_offering_id, class_section_id)`.
- Index `class_sections(academic_period_id, course_id)`.
- Index `timetable_entries(class_section_id, is_deleted)`.
- Partial unique index on live schedule identity:

```text
unique (class_section_id, day_of_week, start_time, end_time, classroom_id)
where is_deleted = false
```

- Preserve the existing `(course_id, academic_period_id, section_code)` unique constraint. PostgreSQL permits multiple null `section_code` values, and `source_key` prevents duplicate import rows.
- Add a check that `program_offerings` and their sections share the same academic period during import validation, not by a cross-table database trigger.

### 2.4 Internal key policy

Keys are deterministic and versioned:

```text
period     ref:v1:period:<source semester id>
offering   ref:v1:offering:<source offering id>
course     ref:v1:course:<normalised course name>
room       ref:v1:room:<room code>
section    ref:v1:section:<sha256(semester|course|sorted offering ids)[:20]>
session    ref:v1:session:<sha256(semester|course|day|start|end|room|sorted offering ids)[:24]>
raw row    ref:v1:raw:<sha256(semester|offering id|raw row ordinal)[:20]>
```

Rules:

- `ref:v1:` is provenance, not an official identifier.
- Keys are stable across re-imports of the same source.
- They are not placed in `courses.code`, `class_sections.section_code` or any API field labelled “code”.
- They may be returned only to management tooling as `source_key`-labelled metadata, never as an official code.
- A source key collision aborts the dry run; no automatic suffixing.

### 2.5 Period/format preservation

`timetable_formats.definition_json` stores the source’s full format definitions. For 2026 Autumn:

- `academic_periods.source_timetable_format = 'standard8'` preserves the contradictory declaration.
- `academic_periods.timetable_format_code = 'block4'` is the resolved value.
- `academic_periods.timetable_format_note` records that all 23 Autumn rows use block labels or unions and no single-period `7`.

The existing `2026-FALL` period is only updated with these reference fields after the period mapping is approved. Its existing name, code and dates are not rewritten by the import.

---

## 3. Migration plan

### 3.1 Revision

One Alembic revision after the current head `9a1f2b3c4d5e`.

Proposed revision file:

`apps/api/alembic/versions/<generated_revision>_scu_timetable_reference_schema.py`

`down_revision = "9a1f2b3c4d5e"`. The revision identifier is generated at implementation time; no revision is created now.

### 3.2 Upgrade sequence

1. Create `timetable_formats`, `timetable_slots`, `academic_import_batches`, `academic_import_rows`.
2. Create `program_offerings` and `class_section_program_offerings`.
3. Add provenance/nullable columns to `academic_periods`, `courses`, `classrooms`, `class_sections`, `timetable_entries`.
4. Alter `courses.code`, `class_sections.section_code`, `classrooms.capacity` to nullable.
5. Alter `courses.credits` and `class_sections.capacity` to nullable; U3/U4 are approved.
6. Add unique/index constraints and the partial live-schedule uniqueness index.
7. Seed `timetable_formats` (2 rows) and `timetable_slots` (11 observed format/label pairs; full definitions remain in `definition_json`).
8. Do **not** import semesters, offerings, courses, rooms, sections, timetable entries or enrollments in this migration.

The migration is data-free for academic records. Seeding two formats and their slot labels is reference configuration, not university academic data.

### 3.3 Downgrade sequence

- Refuse downgrade if any `academic_import_batches.status = 'APPLIED'`.
- Drop join table, then `program_offerings`, then import staging tables, then format/slot tables.
- Drop added columns, indexes and nullable changes.
- Do not delete or rewrite existing legacy rows.
- After downgrade, verify the original counts: 4 majors, 3 programs, 7 courses, 2 periods, 5 classrooms, 5 sections, 6 timetable entries, 24 enrollments.

### 3.4 Pre-migration checks

- `alembic heads` is exactly `9a1f2b3c4d5e`.
- Database backup completed and restore tested on a disposable copy.
- Existing counts match the verified snapshot.
- No conflicting `source_key` columns/tables exist.
- Existing timetable entries have no duplicate live `(section, day, start, end, room)` tuples that would block the partial unique index.
- `courses.code` nullability change does not conflict with existing unique indexes.

---

## 4. Source-to-database mapping

### 4.1 Field map

| Source field | Target | Rule |
|---|---|---|
| `metadata.source`, `generated`, `updated`, `timezone` | `academic_import_batches` and `academic_import_rows.payload` | Preserve raw provenance; never treat as official dates |
| `timeSlotFormats.*` | `timetable_formats.definition_json` | Store both formats unchanged |
| `semesters[].id` | `academic_periods.source_key` | `ref:v1:period:<id>` |
| `semesters[].name` | `academic_periods.name` | Candidate only |
| `semesters[].nameCN` | `academic_periods.name_zh` | Preserve source Chinese name |
| `semesters[].timeSlotFormat` | `academic_periods.source_timetable_format` | Preserve declared value; do not apply it blindly |
| resolved format | `academic_periods.timetable_format_code` | `block4` for 2026 Autumn; `standard8` otherwise |
| missing semester dates | `academic_periods.start_date` / `end_date` | Remain blocked; no inference |
| `programs[].id` | `program_offerings.source_id` | Source offering identifier; not an official code |
| `programs[].name` | `program_offerings.name` | Preserve full name including cohort suffix |
| `programs[].nameCN` | `program_offerings.name_zh` | Preserve |
| source program parent | `program_offerings.program_id` | Null unless reviewed mapping is approved |
| `schedule[].course` | `courses.name` | One row per distinct label; code null |
| `schedule[].day` | `timetable_entries.day_of_week` | Monday=0 … Sunday=6 |
| `schedule[].session` | `timetable_entries.slot_label` | Preserve exact label; resolved start/end also stored |
| `schedule[].start` / `end` | `timetable_entries.start_time` / `end_time` | Resolved from the correct format |
| `schedule[].location` | `classrooms.room_code` | Room code from source |
| `locations[].building/room/campus` | `classrooms.building/campus` | `room_code` remains the source key |
| no source capacity | `classrooms.capacity` | Null approved |
| no source section code | `class_sections.section_code` | Null approved; use internal `source_label` |
| no source course code | `courses.code` | Null approved |
| no source credits | `courses.credits` | Null approved (U3) |
| no source section capacity | `class_sections.capacity` | Null approved (U4) |

### 4.2 Period mapping

| Source | Proposed target | Status |
|---|---|---|
| `2026-autumn` | existing `2026-FALL` | Candidate only; requires confirmation that this is the same period |
| `2026-spring` | new period | Blocked until dates and official period code are supplied |
| `2025-autumn` | new period | Blocked until dates and official period code are supplied |

`2026-FALL` is never assumed to be `2026-autumn` merely because the names resemble each other. The source has no dates to certify the match.

### 4.3 Program mapping

| Source program name | Existing candidate | Proposed action |
|---|---|---|
| Business Administration | `BUS` / `BBA` | Proposal only; six offerings would link to BBA only after approval |
| Computer Science and Technology | `CS` / `BCS` | Proposal only; six offerings would link to BCS only after approval |
| Artificial Intelligence | existing major `english` (AI-named, anomalous code), no program | Leave parent null; do not clean up or reuse the orphan automatically |
| Chinese Language (Elementary Level) | none | Leave parent null; no new program without an official code |
| Chinese Language (Intermediate Level) | none | Leave parent null; no new program without an official code |
| Civil Engineering | none | Leave parent null; no new program without an official code |
| Chinese Language and Literature | none | Leave parent null; no new program without an official code |
| Robotics Engineering | none | Leave parent null; no new program without an official code |

`BAL`, `ENG` and the orphan AI-named major `english` are legacy records. They remain untouched and unmapped.

### 4.4 Record-level mapping

The complete 3-period, 15-offering, 26-course, 11-room, 33-section, 52-session and 9-shared-group mapping is in `docs/scu-timetable-mapping-appendix.md`. It includes every internal key and every held row.

---

## 5. Import procedure

### 5.1 Phase 0 — approval gate

Do not run any of the following until the plan and unresolved decisions are approved:

- schema migration;
- 2026 Autumn period mapping;
- parent-program links;
- shared-section links;
- any course, room, section or timetable insert.

### 5.2 Phase 1 — backup and preflight

1. Take a full database backup and record the restore command.
2. Record the pre-import counts and checksums for all academic tables.
3. Confirm `alembic heads` and that no import batch exists.
4. Confirm the source hash is still `91a36ccea191b0e205f828e138eb5d4d3afe3b9a0ae2aa46b442decc0eeb95d4`.

### 5.3 Phase 2 — schema only

1. Apply the Alembic revision on a disposable database copy.
2. Seed formats and observed slots.
3. Run the schema checks from section 7.
4. Apply to the working database only after the copy passes.

### 5.4 Phase 3 — dry run

Create an `academic_import_batches` row with `status='DRY_RUN'` and `dry_run=true`. Stage:

- 3 period candidates;
- 15 offerings;
- 26 courses;
- 11 rooms;
- 33 derived sections;
- 51 section-offering links;
- 52 unique sessions;
- 76 raw schedule rows, with 24 marked as merged duplicates.

No target academic rows are written during the dry run. Every conflict is written to `academic_import_rows` with a stable error code.

### 5.5 Phase 4 — import order

Only after the dry run is approved:

1. **Periods.** Reuse `2026-FALL` only after its mapping is approved. Create `2025-autumn` and `2026-spring` only when dates and official codes are supplied. Update `2026-FALL` source metadata only; preserve its existing name, code and dates.
2. **Offerings.** Insert all 15 with `program_id` null, except the six BBA/BCS links if separately approved.
3. **Courses.** Insert 26 rows with nullable `credits` (U3 approved). All `code` values are null.
4. **Rooms.** Insert 11 rooms with `capacity=null`, source building/campus, and a scheduling status.
5. **Sections.** Insert 31 live sections; keep the two N103-conflict sections in staging.
6. **Section-offering links.** Insert 49 live links; keep two links held.
7. **Timetable entries.** Insert 48 live sessions; keep four N103 sessions held.
8. **Commit** only after every post-insert assertion passes.

### 5.6 Held records

The held rows are:

- `AI Ethics (International)` — Monday and Wednesday, 10:20–12:00, N103;
- `AI Thinking and Ethics (International)` — Monday and Wednesday, 10:20–12:00, N103.

They remain in `academic_import_rows` with `action='HELD'` and `error_code='N103_CONFLICT_UNRESOLVED'`. They are not inserted into `class_sections`, `class_section_program_offerings` or `timetable_entries`. They are not merged.

### 5.7 Idempotency

- Re-running the same source hash must produce zero new rows.
- A matching `source_key` with identical payload is `SKIP`.
- A matching `source_key` with a changed payload is `CONFLICT`; it must not overwrite.
- Import-owned rows are identified by `import_batch_id`; legacy rows have null.
- No import path deletes a legacy row.

### 5.8 Rollback

**Before commit:** roll back the database transaction; the staging batch remains available for diagnosis.

**After commit:**

1. Mark the batch `ROLLED_BACK`.
2. Delete import-owned join rows, timetable entries, sections, courses, rooms and offerings in reverse dependency order.
3. Delete only periods created by the batch. Restore `2026-FALL` metadata from the batch snapshot if it was updated.
4. Keep `academic_import_rows` for audit.
5. Never delete enrollments, attendance, assessments, grades or academic history.
6. Re-run the pre-import counts and assert equality.

The migration downgrade remains blocked while an `APPLIED` batch exists. This prevents dropping the schema while imported records still reference it.

---

## 6. Expected post-import counts

### 6.1 All periods and both additional nullability approvals

Assumes:

- `2026-autumn` maps to existing `2026-FALL`;
- dates and official codes are supplied for 2025 Autumn and 2026 Spring;
- U3 (nullable credits) and U4 (nullable section capacity) are approved;
- BBA/BCS parent proposals remain unapplied unless separately approved.

| Entity | Before | Imported live | Held in staging | After |
|---|---:|---:|---:|---:|
| Academic periods | 2 | 2 | 0 | **4** (including legacy `VFY1`) |
| Majors | 4 | 0 | 0 | **4** |
| Programs | 3 | 0 | 0 | **3** |
| Program offerings | 0 | 15 | 0 | **15** |
| Courses | 7 | 26 | 0 | **33** |
| Classrooms | 5 | 11 | 0 | **16** |
| Class sections | 5 | 31 | 2 | **36** live; 2 held |
| Section-offering links | 0 | 49 | 2 | **49** live; 2 held |
| Timetable entries | 6 | 48 | 4 | **54** live; 4 held |
| Enrollments | 24 | 0 | 0 | **24** |
| Attendance / assessments / grades / history | 0 | 0 | 0 | **0** |

Source coverage: **48/52 sessions, 31/33 sections, 15/15 offerings, 26/26 courses, 11/11 rooms**. All 76 raw rows are staged and accounted for. The 24 merged rows are represented by 9 shared session identities across 7 canonical sections, not lost.

`program_id` links: **0 applied by default**; **6 BBA/BCS proposals** may be applied only after approval. No new major or program rows.

### 6.2 If 2025/2026 dates remain unresolved

Only 2026 Autumn can be imported, and only if `2026-autumn → 2026-FALL` is approved:

| Entity | After |
|---|---:|
| Periods | **2** (`2026-FALL`, `VFY1`) |
| Program offerings | **6** |
| Courses | **12** (7 existing + 5 Autumn) |
| Classrooms | **11** (5 existing + 6 Autumn) |
| Class sections | **14** (5 existing + 9 Autumn) |
| Timetable entries | **20** (6 existing + 14 Autumn) |
| Enrollments | **24** |

2025 Autumn and 2026 Spring remain fully staged, with no period, offering, course, room, section or session rows. Their dates are not guessed.

### 6.3 U3/U4 resolution

- `courses.credits` and `class_sections.capacity` are nullable.
- Unknown source values are stored as `NULL`; no invented default is written.
- Existing non-null legacy values remain unchanged.

### 6.4 If 2026 Autumn is not mapped to 2026-FALL

No period in the source can be created without dates/approval. The complete import is blocked; nothing is published.

---

## 7. Validation checks

### 7.1 Dry-run assertions

- Source SHA-256 matches.
- 3 period candidates, 15 offerings, 26 courses, 11 rooms, 33 sections, 51 links, 52 sessions, 76 raw rows.
- 24 raw rows are marked merged; 9 shared session identities across 7 canonical sections match those merges exactly.
- Every session has a resolvable format/label and clock interval; 0 unresolved.
- Every session belongs to exactly one derived section and one or more offerings.
- Every offering belongs to exactly one period.
- No section contains offerings from different periods.
- No duplicate `source_key` within any entity.
- 2026 Autumn: 0 rows with `source_timetable_format` applied; all 23 raw rows resolve under block4.
- 2026 Spring and 2025 Autumn: all single-`7` rows resolve under standard8.
- Nine shared session identities: seven canonical sections (two sections have two sessions); same course/time/room; structural pass recorded for each.
- N103: exactly four sessions and two sections held; zero live inserts.
- Room/time collision check on live proposals: zero collisions.
- Every period that would be created has non-null dates and an official code.
- Existing 24 enrollments and all legacy IDs are present and unchanged.
- No source key is written into an official code column.

### 7.2 Post-import assertions

- Exact counts from section 6.1 or the approved partial scenario.
- `source_key` uniqueness and referential integrity for all imported rows.
- `academic_periods` created by the batch have non-null dates and codes.
- `program_offerings` count is 15; `program_id` is null unless approved.
- `courses.code` is null for all 26; `class_sections.section_code` is null for all 31 live imported sections; `classrooms.capacity` is null for all 11 new rooms.
- All 31 live sections have at least one live timetable entry.
- All 49 live section-offering links point to a section and offering in the same period.
- 4 held sessions and 2 held sections are absent from live tables and present in staging.
- Live timetable has no N103 duplicate booking.
- `SELECT count(*) FROM enrollments` is still 24; no imported enrollment exists.
- Legacy `VFY1`, `BAL`, `ENG`, `english`, `CS101`, `CS201`, `CS301`, `BA101`, `BA201`, `EN101`, `EN201` and the six legacy timetable entries are byte-for-byte unchanged except for approved period metadata on `2026-FALL`.

### 7.3 Retrieval assertions

- Selected period returns only its classes and timetable.
- No API call returns a mixed-period timetable by default.
- Program filter returns a shared section once, not once per offering.
- Saturday and Sunday entries are returned and rendered.
- Student sees only own data; teacher sees only assigned sections; admin/management sees all.
- Historical period selection works for completed enrollments.
- Empty period returns an empty state, not a mixed-period grid.

---

## 8. Student and staff timetable retrieval changes

### 8.1 Period resolution

Add one service helper used by every timetable path:

```text
resolve_period(db, period_id, *, allow_all=False)
  - if period_id supplied: verify it exists, return it
  - else: return the ACTIVE period ordered by start_date desc
  - if no ACTIVE period: return an explicit empty/409 state, never all periods
```

`list_timetable_entries` must no longer behave differently depending on whether `period_id` is supplied. If no period is supplied, the resolved active period is used. A separate `all_periods=true` is allowed only for management with `academic.manage_timetable`; ordinary staff never receive mixed periods.

### 8.2 Student overview and timetable

`GET /api/v1/academics/students/{student_id}`:

- Add optional `period_id`.
- Resolve the active period when absent.
- Filter enrolled classes and timetable entries by the selected period.
- Add `selected_period` and `is_current` while retaining `current_period` for compatibility.
- Default statuses for the active period: `ENROLLED`.
- Historical view statuses: `ENROLLED` and `COMPLETED`; exclude `DROPPED` and `WITHDRAWN` unless a transcript-specific endpoint is added.
- Return no classes from other periods.

`GET /api/v1/academics/students/{student_id}/timetable`:

- Keep `period_id`, but default to the active period rather than all periods.
- Join through the student’s period-filtered enrollments.
- Preserve the existing student/teacher scope check.
- Include period code/name, `slot_label`, format and program offering names in the response.

The profile page should query the selected period, not only once on initial load. The current `getStudentAcademic(studentId)` and `getStudentTimetable(studentId)` calls become `(studentId, periodId)`.

### 8.3 Staff academic dashboard

`GET /api/v1/academics/timetable`:

- Add `program_offering_id`, `course_id` and optional `day_of_week` filters.
- Join `class_section_program_offerings` only when `program_offering_id` is supplied.
- Return each shared section once; use `DISTINCT` or an `EXISTS` subquery.
- Default to the selected/active period.
- Apply teacher scope: a teacher receives only entries for assigned class sections. Admin/management receive all.
- Include `academic_period_id`, `period_code`, `format_code`, `slot_label` and program offering summaries.

`GET /api/v1/academics/classes`:

- Add `program_offering_id` and `course_id`.
- Apply the same teacher scope.
- Return `section_code: null` when no official code exists and `source_label` separately.

New endpoint:

```text
GET /api/v1/academics/program-offerings?period_id=<uuid>&search=<text>
```

- Requires `academic.view`.
- Returns `id`, `name`, `name_zh`, `program_id`, `academic_period_id`, and parent program name when mapped.
- Does not expose internal `source_key` as a code.
- Used by the dashboard program selector and class cards.

### 8.4 Response/schema changes

- `CourseResponse.code: str | null`; `credits: int | null`; add `name_zh`.
- `ClassroomResponse.capacity: int | null`; add `campus`.
- `ClassSectionResponse.section_code: str | null`; add `source_label`, `program_offerings`, `capacity: int | null`.
- `ClassSectionBrief.section_code: str | null`; add `program_offerings`.
- `TimetableEntryResponse` add `academic_period_id`, `period_code`, `format_code`, `slot_label`, `program_offerings`.
- Do not add raw `source_key` to public response models.
- Regenerate `apps/web/src/types/generated/api.d.ts` and then update `apps/web/src/types/academic.ts`.

### 8.5 Frontend timetable grid

- Replace the fixed five-key `WEEKDAY_KEYS` with all seven keys (`mon`…`sun`).
- Derive visible columns from the selected period’s entries, always including Monday–Friday and adding Saturday/Sunday only when present. This preserves the current layout for weekday-only periods while making the existing Saturday `CS201-A` visible.
- Use a dynamic grid template and minimum width; do not hardcode `repeat(5, …)`.
- Add Saturday/Sunday options to `TimetableEntryDialog`; the API already accepts `day_of_week` 0–6.
- Keep the `todayIndex` calculation `(new Date().getDay() + 6) % 7`.
- Render `slot_label` alongside start/end time so block4 and standard8 sessions remain legible.
- Add a format badge from the selected period (`block4` / `standard8`).
- Extract the grid into one shared component used by the academic dashboard and student timetable if practical, to avoid divergent weekend behavior.

### 8.6 Frontend filters and fallbacks

- Add a period selector to the academic dashboard; default to the active period, not all periods.
- Add a program-offering selector and course filter; selecting an offering must not duplicate shared sections.
- Add a period selector to the student Academic and Timetable tabs. Historical selection uses `period_id` and includes completed enrollments.
- Display fallbacks:
  - course code null → course name;
  - section code null → `source_label` or offering names, never an internal key;
  - credits null → “Not supplied”;
  - capacity null → “Not supplied”.
- Add a visible `Unresolved dates`/`Held — N103 conflict` badge in management-only views for staged rows; do not show held rows as confirmed bookings.
- Update admin forms and validation:
  - course code optional;
  - section code optional;
  - classroom capacity optional;
  - credits optional (U3 approved);
  - section capacity optional (U4 approved).
- Preserve all current permissions; no new permission is required for reading filtered timetables. Mutations continue to require the existing `academic.manage_*` permissions.

### 8.7 Query and performance rules

- Apply period filter at the `ClassSection` join, not in Python after loading entries.
- Filter program offerings via `EXISTS`/join before ordering and pagination.
- Use the new indexes for `(period_id, course_id)` and offering joins.
- Keep response pagination for classes and program offerings; timetable remains a bounded selected-period list.
- Shared sections must appear once per section, not once per offering.

---

## 9. Unresolved institutional decisions

### U1 — Dates and period identity

- Start/end dates for `2025-autumn` and `2026-spring`.
- Official period codes for both.
- Whether `2026-autumn` is officially the existing `2026-FALL` period.
- Whether `VFY1` should remain selectable or be hidden as a verification period.

**Blocks:** period creation for two semesters; all their offerings, sections and sessions.

### U2 — Parent program mapping

- Confirm the proposed Business Administration → `BBA` and Computer Science and Technology → `BCS` links.
- Decide whether the orphan AI-named major `english` is the canonical AI major despite its code.
- Decide whether the six remaining source program names are official programs or only cohort/class labels.
- Confirm the disposition of legacy `BAL`/`ENG`.
- No new major/program code will be invented.

**Blocks:** all non-null `program_offerings.program_id` assignments. It does not block importing the offering records with a null parent.

### U3 — Course credits (approved)

- `courses.credits` is nullable.
- Source-missing values are stored as `NULL`; no credits are invented.

### U4 — Class-section capacity (approved)

- `class_sections.capacity` is nullable.
- Source-missing values are stored as `NULL`; no capacities are invented.

### U5 — N103 conflict

- Determine whether `AI Ethics (International)` and `AI Thinking and Ethics (International)` are a combined lecture, equivalent courses for two cohorts, or two separate bookings.
- If separate, confirm which course moves room/time.
- Until resolved, the four sessions and two sections remain held; no merge, no confirmed booking.

### U6 — Shared-delivery sign-off

- Confirm each of the seven canonical shared sections listed in the appendix is genuinely shared.
- The structural test passes for all nine shared session identities that make up those seven sections; this is the institutional confirmation required before join rows are committed.
- If one is not shared, split it into separate sections; do not silently preserve the join.

### U7 — Group 1 / Group 2 interpretation

- Confirm whether `Introduction to the Major (Group 1)` and `(Group 2)` are distinct courses, sections of one course, or cohort labels.
- Current plan preserves them as distinct source course labels and candidate sections.

### U8 — Missing academic attributes

- Chinese course names.
- Teacher assignments.
- Cohort/entry year.
- Week ranges.
- Classroom capacities if available.
- Official course codes and section codes if available.

These values are not inferred and are not required to create the staged reference records, except where a field remains non-nullable.

### U9 — Publication policy for unverified records

- Confirm that source-only records with null official codes may appear in staff/student timetable views.
- Confirm that internal `ref:v1:` keys are never displayed as official identifiers or exported as official codes.

### U10 — Legacy period/record handling

- Keep `VFY1`, `BAL`, `ENG`, the orphan AI major and all legacy courses/sections/timetable entries.
- Decide whether they should be hidden from default academic views or retained as visible legacy data.
- No deletion is proposed.

---

## 10. Approval gate

No migration, import, API change or UI change should be applied until the user approves:

1. the schema in section 2;
2. the approved nullable credits/section-capacity fields U3/U4;
3. the period mapping/date plan U1;
4. the parent-program proposals U2;
5. the shared-group sign-off U6;
6. the N103 hold U5;
7. the retrieval/security changes in section 8.

**Current live state remains unchanged:** 4 majors, 3 programs, 7 courses, 2 periods, 5 classrooms, 5 sections, 6 timetable entries and 24 enrollments.
