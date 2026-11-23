# SCU Timetable — Domain Audit and Complete Subject-to-Program Map

**Status:** source and implementation audit. No live academic record was imported or changed. No schema change was made after the additive revision already present on the development database.

**Source:** `docs/scu-timetable-reference.json`  
**Source SHA-256:** `91a36ccea191b0e205f828e138eb5d4d3afe3b9a0ae2aa46b442decc0eeb95d4`  
**Machine-readable map:** `docs/scu-timetable-domain-map.json`

---

## 1. Answer to the domain-model question

The intended hierarchy is:

```text
INTAKE PERIOD -> MAIN PROGRAM / MAJOR OFFERING -> SUB-COURSES -> TIMETABLE SESSIONS
```

| Layer | Current representation | Fit | Finding |
|---|---|---|---|
| Intake period | `academic_periods` | Partial | Correct concept, but all three periods still lack approved source dates; 2025 Autumn and 2026 Spring also lack codes. |
| Main program offering | `program_offerings` | **Correct** | Period-specific source offering; `program_id` remains nullable because no canonical parent was supplied. |
| Sub-course | `courses` + `class_sections` | **Mostly correct** | Course ownership is represented by the section-to-offering link, not by `courses.program_id`. |
| Shared class | `class_sections` + `class_section_program_offerings` | **Correct** | One section can be linked to several offerings and has one set of timetable rows. |
| Student intake/program membership | **Missing** | **Needs adjustment** | `students.program_id` points at the legacy `programs` table, not a period-specific offering. |
| Student timetable | enrollment-only lookup | **Needs adjustment** | It filters by enrolled section and period but does not require the section to belong to the student’s intake offering. |

### `program_offerings` and `class_section_program_offerings`

They are the right structures for the clarified model:

- A `program_offerings` row is one intake’s main program. The intake is its `academic_period_id`; the main program is its source name and optional canonical `program_id`.
- A `class_sections` row is one canonical teaching section for a course in a period.
- `class_section_program_offerings` is the many-to-many link. If four programs genuinely share one class, the section has four links and still has one set of timetable bookings.
- `courses.program_id` is a legacy scalar. It cannot describe a shared course and must remain `NULL` for imported courses. The import already does this.

### Required adjustment before live import (not applied)

A student needs a nullable, explicit link to the period-specific offering. The smallest change consistent with the source is:

```text
students.program_offering_id  uuid  null  references program_offerings(id)
```

No default, backfill, guessed parent program or invented intake date. Existing students remain `NULL` and keep their legacy `program_id` / `major_id`. The offering already supplies both the intake period and the main program.

Proposed read rule:

1. Resolve the selected intake period.
2. Require `student.program_offering_id` to belong to that period.
3. Return sections linked to that offering, including a shared section only once.
4. Do not add a section merely because the student has an enrollment elsewhere; an enrollment may not widen visibility beyond the offering.
5. For legacy students with no offering link, retain the current enrollment-based fallback so the existing 24 enrollments remain visible and unchanged.

This change is not implemented and no migration has been written because the revised model needs your approval.

### Staff scope

The API already supports filtering classes and timetable entries by `period_id`, `program_offering_id` and `course_id`. Teachers are restricted to their active `teacher_assignments`; management and admin are unrestricted. The academic page now exposes the subject filter as well as intake and program, so staff can isolate one intake/program/subject without mixing unrelated schedules.

---

## 2. Complete source subject map

The map contains 51 offering–subject pairs across 15 offerings and 26 distinct subject labels. Every row below is one source subject inside one intake and one main program offering. The `Delivery` column is based only on exact source identity: same period, course, day, slot and room. It does not invent a shared relationship from a similar name.

### 2026 Autumn (`2026-autumn`)

| Main program offering | Subject | Source rows | Delivery | Canonical section |
|---|---|---:|---|---|
| Chinese Language (Elementary Level) 1 (`chinese-elementary-2026a`) | Chinese Language | 3 | Exclusive | `ref:v1:section:ca3eee001d167c63c508` |
| Chinese Language (Intermediate Level) 1 (`chinese-intermediate-2026a`) | Chinese Language | 3 | Exclusive | `ref:v1:section:d1d486f9e2d28b85932f` |
| Artificial Intelligence (International) 1 (`ai-2026a`) | Chinese Language | 2 | Shared with `business-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` |
| Artificial Intelligence (International) 1 (`ai-2026a`) | Introduction to the Major | 1 | Exclusive | `ref:v1:section:083707aa1428c6e8bbfc` |
| Artificial Intelligence (International) 1 (`ai-2026a`) | Advanced Mathematics (A) 1 | 1 | Shared with `business-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` |
| Civil Engineering (International) 1 (`civil-2026a`) | Chinese Language | 2 | Shared with `ai-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` |
| Civil Engineering (International) 1 (`civil-2026a`) | Introduction to the Major | 1 | Exclusive | `ref:v1:section:0d226101ebc3e831f8cc` |
| Civil Engineering (International) 1 (`civil-2026a`) | Advanced Mathematics (A) 1 | 1 | Shared with `ai-2026a`, `business-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` |
| Business Administration (International) 1 (`business-2026a`) | Chinese Language | 2 | Shared with `ai-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` |
| Business Administration (International) 1 (`business-2026a`) | Introduction to the Major | 1 | Exclusive | `ref:v1:section:81922c31678aaac0cb02` |
| Business Administration (International) 1 (`business-2026a`) | Advanced Mathematics (A) 1 | 1 | Shared with `ai-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` |
| Computer Science and Technology (International) 1 (`cs-2026a`) | Chinese Language | 2 | Shared with `ai-2026a`, `business-2026a`, `civil-2026a` | `ref:v1:section:006815c6eddba07f37c6` |
| Computer Science and Technology (International) 1 (`cs-2026a`) | Introduction to the Major (Group 2) | 1 | Exclusive | `ref:v1:section:0f469177db9393732656` |
| Computer Science and Technology (International) 1 (`cs-2026a`) | Advanced Mathematics (A) 1 | 1 | Shared with `ai-2026a`, `business-2026a`, `civil-2026a` | `ref:v1:section:866b54b20860e34c43b2` |
| Computer Science and Technology (International) 1 (`cs-2026a`) | Introduction to the Major (Group 1) | 1 | Exclusive | `ref:v1:section:3c722ac84007113ae7a7` |

### 2026 Spring (`2026-spring`)

| Main program offering | Subject | Source rows | Delivery | Canonical section |
|---|---|---:|---|---|
| Civil Engineering (International) 1 (`civil-engineering-2026s`) | Architectural Mechanics (International) | 2 | Exclusive | `ref:v1:section:f55345e90e5648c85bbe` |
| Civil Engineering (International) 1 (`civil-engineering-2026s`) | Chinese, Major 1-2 (International) | 1 | Shared with `ai-2026s`, `business-2026s`, `cs-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` |
| Civil Engineering (International) 1 (`civil-engineering-2026s`) | Civil Engineering Drawing (International) | 2 | Exclusive | `ref:v1:section:96d3623b2f2522083701` |
| Civil Engineering (International) 1 (`civil-engineering-2026s`) | University Physics A 1 (International) | 1 | Shared with `ai-2026s`, `cs-2026s` | `ref:v1:section:17bfebc7714fdef97beb` |
| Civil Engineering (International) 1 (`civil-engineering-2026s`) | MATHS (A2) (International) | 1 | Shared with `ai-2026s`, `business-2026s`, `cs-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` |
| Artificial Intelligence (International) 1 (`ai-2026s`) | Python Programming (International) | 2 | Exclusive | `ref:v1:section:db0fad16f1abbd622b3f` |
| Artificial Intelligence (International) 1 (`ai-2026s`) | Prompt Engineering (International) | 2 | Exclusive | `ref:v1:section:423235516af30c85b346` |
| Artificial Intelligence (International) 1 (`ai-2026s`) | Chinese, Major 1-2 (International) | 1 | Shared with `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` |
| Artificial Intelligence (International) 1 (`ai-2026s`) | University Physics A 1 (International) | 1 | Shared with `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:17bfebc7714fdef97beb` |
| Artificial Intelligence (International) 1 (`ai-2026s`) | MATHS (A2) (International) | 1 | Shared with `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | Fundamentals of Programming (International) | 1 | Exclusive | `ref:v1:section:6c0ec4dd7daafe325d13` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | Chinese, Major 1-2 (International) | 1 | Shared with `ai-2026s`, `business-2026s`, `civil-engineering-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | Discrete Mathematics (International) | 2 | Exclusive | `ref:v1:section:4d6558ba9649b3b9c743` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | University Physics A 1 (International) | 1 | Shared with `ai-2026s`, `civil-engineering-2026s` | `ref:v1:section:17bfebc7714fdef97beb` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | MATHS (A2) (International) | 1 | Shared with `ai-2026s`, `business-2026s`, `civil-engineering-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` |
| Computer Science and Technology (International) 1 (`cs-2026s`) | Digital Electronic Technology | 2 | Exclusive | `ref:v1:section:276c1eca28c0bf95889f` |
| Chinese Language and Literature (International) 1 (`chinese-lit-2026s`) | Chinese, Major 1-2 (International) | 3 | Exclusive | `ref:v1:section:ec8ba49b25d82bc7a34e` |
| Business Administration (International) 1 (`business-2026s`) | Management (International) | 1 | Exclusive | `ref:v1:section:4c6835e32af575f4d12c` |
| Business Administration (International) 1 (`business-2026s`) | Human Resource Management (International) | 2 | Exclusive | `ref:v1:section:4fb87df7bf87e94de6a9` |
| Business Administration (International) 1 (`business-2026s`) | Chinese, Major 1-2 (International) | 1 | Shared with `ai-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` |
| Business Administration (International) 1 (`business-2026s`) | MATHS (A2) (International) | 1 | Shared with `ai-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` |

### 2025 Autumn (`2025-autumn`)

| Main program offering | Subject | Source rows | Delivery | Canonical section |
|---|---|---:|---|---|
| Artificial Intelligence (International) 1 (`ai-2025a`) | AI Ethics (International) | 2 | **HELD — N103 conflict** | `ref:v1:section:b3781e87f3fe230d6186` |
| Artificial Intelligence (International) 1 (`ai-2025a`) | Chinese, Major 2-1 (International) | 2 | Shared with `business-2025a`, `cs-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` |
| Artificial Intelligence (International) 1 (`ai-2025a`) | Prompt Engineering (International) | 1 | Shared with `robotics-2025a` | `ref:v1:section:c4489c8850dfd91fbca5` |
| Computer Science and Technology (International) 1 (`cs-2025a`) | Data Structures and Algorithms (International) | 1 | Exclusive | `ref:v1:section:9925cc2345c7b1446b7a` |
| Computer Science and Technology (International) 1 (`cs-2025a`) | Computer Organization Principles (International) | 2 | Exclusive | `ref:v1:section:e81f00eff6e4ca807dc4` |
| Computer Science and Technology (International) 1 (`cs-2025a`) | Chinese, Major 2-1 (International) | 2 | Shared with `ai-2025a`, `business-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` |
| Business Administration (International) 1 (`business-2025a`) | Organizational Behavior (International) | 1 | Exclusive | `ref:v1:section:15be152b200c5f48addc` |
| Business Administration (International) 1 (`business-2025a`) | Business and Technology (International) | 1 | Exclusive | `ref:v1:section:d1dd8dab20738f4d6232` |
| Business Administration (International) 1 (`business-2025a`) | Human Resource Management (International) | 2 | Exclusive | `ref:v1:section:1e7cd6fd797e2370bb54` |
| Business Administration (International) 1 (`business-2025a`) | Chinese, Major 2-1 (International) | 2 | Shared with `ai-2025a`, `cs-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` |
| Business Administration (International) 1 (`business-2025a`) | Microeconomics (International) | 1 | Exclusive | `ref:v1:section:8d77ce560b6b0ecb4cd9` |
| Robotics Engineering (International) 1 (`robotics-2025a`) | AI Thinking and Ethics (International) | 2 | **HELD — N103 conflict** | `ref:v1:section:72b4ca9503f2e4703c88` |
| Robotics Engineering (International) 1 (`robotics-2025a`) | Fundamentals of Electronic Technology (International) | 1 | Exclusive | `ref:v1:section:5b7981573088f2d0a107` |
| Robotics Engineering (International) 1 (`robotics-2025a`) | Chinese, Major 2-1 (International) | 2 | Shared with `ai-2025a`, `business-2025a`, `cs-2025a` | `ref:v1:section:feeccdd0c056db240de2` |
| Robotics Engineering (International) 1 (`robotics-2025a`) | Prompt Engineering (International) | 1 | Shared with `ai-2025a` | `ref:v1:section:c4489c8850dfd91fbca5` |

---

## 3. Shared sections (canonical delivery)

7 canonical sections account for 9 shared source session identities and 24 collapsed duplicate raw rows.

| # | Intake | Subject | Sessions | Linked offerings | Canonical section | Status |
|---:|---|---|---|---|---|---|
| 1 | 2025-autumn | Chinese, Major 2-1 (International) | Thursday `3-4` N107<br>Wednesday `1-2` N107 | `ai-2025a`, `business-2025a`, `cs-2025a`, `robotics-2025a` | `ref:v1:section:feeccdd0c056db240de2` | Ready for sign-off |
| 2 | 2025-autumn | Prompt Engineering (International) | Thursday `5-8` N103 | `ai-2025a`, `robotics-2025a` | `ref:v1:section:c4489c8850dfd91fbca5` | Ready for sign-off |
| 3 | 2026-autumn | Advanced Mathematics (A) 1 | Thursday `5-8` G310 | `ai-2026a`, `business-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:866b54b20860e34c43b2` | Ready for sign-off |
| 4 | 2026-autumn | Chinese Language | Monday `1-2` G410<br>Wednesday `7-8` G310 | `ai-2026a`, `business-2026a`, `civil-2026a`, `cs-2026a` | `ref:v1:section:006815c6eddba07f37c6` | Ready for sign-off |
| 5 | 2026-spring | Chinese, Major 1-2 (International) | Wednesday `1-4` N106 | `ai-2026s`, `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:ecfbfb8b0649fe4fb9ea` | Ready for sign-off |
| 6 | 2026-spring | MATHS (A2) (International) | Friday `1-4` N106 | `ai-2026s`, `business-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:f5b5ecfb8ca150a82568` | Ready for sign-off |
| 7 | 2026-spring | University Physics A 1 (International) | Thursday `5-8` N107 | `ai-2026s`, `civil-engineering-2026s`, `cs-2026s` | `ref:v1:section:17bfebc7714fdef97beb` | Ready for sign-off |

**Shared subject labels:** `Advanced Mathematics (A) 1`, `Chinese Language`, `Chinese, Major 1-2 (International)`, `Chinese, Major 2-1 (International)`, `MATHS (A2) (International)`, `Prompt Engineering (International)`, `University Physics A 1 (International)`.

`Chinese Language` (2026 Autumn) and `Chinese, Major 1-2 (International)` (2026 Spring) are **partially shared**: some offerings share one canonical section, while another offering has a separate section. The per-program table above shows which is which.

**Exclusive subject labels:** `AI Ethics (International)`, `AI Thinking and Ethics (International)`, `Architectural Mechanics (International)`, `Business and Technology (International)`, `Civil Engineering Drawing (International)`, `Computer Organization Principles (International)`, `Data Structures and Algorithms (International)`, `Digital Electronic Technology`, `Discrete Mathematics (International)`, `Fundamentals of Electronic Technology (International)`, `Fundamentals of Programming (International)`, `Human Resource Management (International)`, `Introduction to the Major`, `Introduction to the Major (Group 1)`, `Introduction to the Major (Group 2)`, `Management (International)`, `Microeconomics (International)`, `Organizational Behavior (International)`, `Python Programming (International)`.

`Introduction to the Major` is the same label in three 2026 Autumn programs, but the source gives each program a different day, time and room. They are therefore three exclusive sections, not a shared class. `Introduction to the Major (Group 1)` and `(Group 2)` are distinct labels under the same CS offering.

---

## 4. Uncertain or blocked mappings

| Item | Status | Reason |
|---|---|---|
| All 15 offering-to-canonical-`programs` links | **Unsettled** | The source supplies program names, not official parent-program identifiers. `program_id` stays `NULL`; no parent is invented. |
| Semester dates and official period codes | **Blocked** | All three source periods lack dates. 2025 Autumn and 2026 Spring also lack approved codes. `2026-FALL` is only a candidate for 2026 Autumn, not certified. |
| N103 in 2025 Autumn | **Held** | `AI Ethics (International)` and `AI Thinking and Ethics (International)` occupy N103 at the same times. Two sections and four sessions remain held. |
| “Chinese Language Level 1” / “Chinese Language Intermediate Level” | **Name mismatch** | Source names are `Chinese Language (Elementary Level) 1` and `Chinese Language (Intermediate Level) 1`. The source names are used here; no rename is applied. |
| “Chinese Language and Literature (International)” | **Name mismatch** | Source name is `Chinese Language and Literature (International) 1`. |
| Group 1 / Group 2 | **Unsettled** | The source gives two distinct course labels under CS; whether they are cohorts, sections or separate courses needs confirmation. |
| Official course/section codes, credits, capacities | **Not supplied** | Stored as `NULL` on import; no defaults. |

No source subject sharing is uncertain when the exact source identity is used. Partial sharing is shown explicitly instead of being rounded up to “shared”.

---

## 5. Data preservation and database state

Live development database counts before and after the audit:

| Entity | Count |
|---|---:|
| Majors | 4 |
| Programs | 3 |
| Courses | 7 |
| Academic periods | 2 |
| Classrooms | 5 |
| Class sections | 5 |
| Timetable entries | 6 |
| Enrollments | **24** |
| Import batches / rows | **0 / 0** |

A custom-format backup was created and restored into a temporary database. The restored counts matched exactly, then the temporary database was removed.

- Backup: `backups/school_portal_pre_domain_audit_20261111-141510.dump`
- SHA-256: `da6c6023893c8f00c77002a45f8cd045cca7c81c6502abed2834df0400363862`
- Restore-list objects: 349
- Development schema remains at `a7b8c9d0e1f2` as instructed; it was not downgraded.
- Production-shaped database remains at `c1d2e3f4a5b6`; read-only verification reports 0 majors, 0 programs, 0 courses, 0 periods, 0 sections and 0 enrollments.

The dev API container was recreated with `RUN_MIGRATIONS=0`; startup does not run Alembic unless that variable is explicitly set to `1`. `/ready` returned 200 after the restart; the schema stayed at `a7b8c9d0e1f2`; the counts above were unchanged; and the startup logs contained no Alembic execution. Migrations remain available deliberately through `make migrate`.

---

## 6. Verification

- Focused backend suite: **53 passed, 1 skipped** (`tests/test_academic_import.py`, `tests/test_academic.py`).
- `pnpm typecheck`: passed.
- `pnpm lint`: passed.
- `pnpm i18n:check`: passed; 1,311 keys in each of en, fr, ru, zh, ar; 135 dynamic keys and 52 error codes covered.
- `git diff --check`: passed.
- Scratch filter check: AI and Civil Engineering resolve `Advanced Mathematics (A) 1` to the same canonical section; AI's shared `Chinese Language` section is distinct from the elementary section; every returned class and timetable row belongs to the selected offering.
- The scratch database also contains two synthetic weekend entries created during the earlier render check, so the Advanced Mathematics section has two scratch rows rather than one imported row. They are not source import records.
- Gated startup check: `/ready` 200, dev schema still `a7b8c9d0e1f2`, counts unchanged, zero import batches/rows, no Alembic execution in the startup log.
- No live academic import was executed.

## 7. Decisions still needed

1. Approve or reject `students.program_offering_id` (or a membership-history alternative).
2. Confirm the seven shared sections, including partial sharing for Chinese Language and Chinese, Major 1-2.
3. Resolve period dates/codes and the N103 conflict before any live import.
4. Confirm whether Group 1/Group 2 are separate classes.
5. Confirm or reject the proposed canonical-program links; until then they stay `NULL`.

