# SCU Timetable Reconciliation Report

**Status:** 2026 Autumn applied in development; 2025 Autumn and 2026 Spring held  
**Source:** `docs/scu-timetable-reference.json`  
**SHA-256:** `91a36ccea191b0e205f828e138eb5d4d3afe3b9a0ae2aa46b442decc0eeb95d4`  
**Machine-readable diff:** `docs/scu-timetable-reconciliation-diff.json`  
**Applied batch:** `0fdf3e09-36ad-41f0-b81c-1118bbaffa21` (development only)  
**Approval:** institutional confirmation still required for the items in section 10

---

## 1. Result

The reference contains **3 semesters, 15 semester-specific program offerings, 8 distinct program names, 26 course labels, 52 unique weekly sessions, 33 candidate sections and 11 rooms**.

### 2026-11 UAT application update

The 2026 Autumn source was applied in the development database against the
existing, dated `2026-FALL` period:

| Applied object | Count |
|---|---:|
| Periods mapped | 1 (`2026-autumn` → `2026-FALL`) |
| Program offerings | 6 |
| Teaching sections | 9 |
| Canonical timetable sessions | 14 |
| Section-offering links | 23 |
| Held sections | 2 (2025 Autumn N103 conflict) |
| Held sessions | 4 (2025 Autumn N103 conflict) |
| Source-only periods | 2 (`2025-autumn`, `2026-spring`) |

Current development totals after the additive import: **1 academic period,
6 majors, 7 programmes, 33 courses, 17 class sections and 22 live timetable
entries** (8 pre-existing legacy entries plus 14 imported 2026 Autumn entries).

Canonical parent mappings applied for the UAT dataset:

| Source offering | Canonical programme | Basis |
|---|---|---|
| `business-2026a` | `BBA` Bachelor of Business Administration | existing programme |
| `cs-2026a` | `BCS` Bachelor of Computer Science | existing programme |
| `ai-2026a` | `AI-INT` Artificial Intelligence (International) | UAT canonical mapping; no official code supplied |
| `civil-2026a` | `CE-INT` Civil Engineering (International) | UAT canonical mapping; no official code supplied |
| `chinese-elementary-2026a` | `CLE-INT` Chinese Language (Elementary Level) | UAT canonical mapping; no official code supplied |
| `chinese-intermediate-2026a` | `CLI-INT` Chinese Language (Intermediate Level) | UAT canonical mapping; no official code supplied |

The four UAT-created parent programmes are marked in their descriptions as
internal mappings, not official institutional programme codes. They must not be
treated as a registry decision.

The two held semesters remain source-only:

- `2025-autumn` has 4 offerings, 16 sessions and the unresolved N103 overlap.
- `2026-spring` has 5 offerings and 22 sessions.
- Neither has official start/end dates. No period or offering was created, so
  neither is selectable in the portal.

### Pre-application baseline (preserved)

The reference contains **3 semesters, 15 semester-specific program offerings, 8 distinct program names, 26 course labels, 52 unique weekly sessions, 33 candidate sections and 11 rooms**.

At the time of the original dry run the live portal contained **2 periods, 4 majors, 3 programs, 7 courses, 5 classrooms, 5 class sections and 6 timetable entries**. The current post-application totals are above; the older figures are retained only as the evidence baseline.

No source record can be matched to a live record by a shared database key. The only candidates are semantic name/period matches, which require explicit approval. Existing academic records are therefore treated as **legacy/unmapped**, not overwritten.

Existing data that must be preserved:

- 24 enrollments
- 0 attendance records
- 0 assessments
- 0 grades
- 0 academic-change history rows
- 0 deleted timetable entries

---

## 2. Timetable-format reconciliation

The source contains a metadata conflict:

- Top-level `timeSlotFormats.block4.description` says: **“Used by 2026 Autumn”**.
- The `2026-autumn` semester record declares `timeSlotFormat: "standard8"`.

The actual schedule labels resolve the conflict:

| Semester | Declared | Session labels present | Resolved format |
|---|---|---|---|
| 2025 Autumn | `standard8` | Singles including `7`; ranges `1-2`, `3-4`, `5-6`, `5-8`, `1-4` | **standard8** |
| 2026 Spring | `standard8` | Single `7`; ranges `1-4`, `3-4`, `5-6`, `5-8` | **standard8** |
| 2026 Autumn | `standard8` | No single periods; only `1-2`, `3-4`, `5-6`, `7-8`, `1-4`, `5-8` | **block4** |

The single-period `7` in 2025 Autumn and 2026 Spring is defined only by `standard8`. The complete absence of single-period sessions in 2026 Autumn, together with the top-level description, supports **block4** for 2026 Autumn. The per-semester `timeSlotFormat` value in the source is therefore considered erroneous; the source file itself has not been edited.

Resolved clock times:

| Label | 2026 Autumn (block4) | 2025 Autumn / 2026 Spring (standard8) |
|---|---|---|
| `1-2` | 08:20–10:00 | 08:20–10:00 |
| `3-4` | 10:20–12:00 | 10:20–12:00 |
| `5-6` | 13:30–15:10 | 13:30–15:10 |
| `7-8` | 15:20–17:00 | 15:20–17:00 |
| `1-4` | 08:20–12:00 | 08:20–12:00 |
| `5-8` | 13:30–17:00 | 13:30–17:00 |
| `7` | not defined | 15:20–16:05 |

All **76** source schedule rows resolve to these times. **0 unresolved rows**.

---

## 3. Source inventory

### Semesters

| Source ID | Name | Chinese name | Offerings | Raw rows | Unique sessions | Format |
|---|---|---|---:|---:|---:|---|
| `2026-autumn` | 2026 Autumn | 2026秋季 | 6 | 23 | 14 | block4 |
| `2026-spring` | 2026 Spring | 2026春季 | 5 | 30 | 22 | standard8 |
| `2025-autumn` | 2025 Autumn | 2025秋季 | 4 | 23 | 16 | standard8 |
| **Total** | | | **15** | **76** | **52** | |

The reduction from 76 rows to 52 sessions is caused by identical course/day/time/room sessions shared by multiple program offerings. There are **9 shared-session groups**, accounting for **24 collapsed duplicate rows**.

### Distinct program names

1. Chinese Language (Elementary Level)
2. Chinese Language (Intermediate Level)
3. Artificial Intelligence
4. Civil Engineering
5. Business Administration
6. Computer Science and Technology
7. Chinese Language and Literature
8. Robotics Engineering

The source uses semester-specific offering IDs, for example:

- `ai-2025a`, `ai-2026s`, `ai-2026a`
- `business-2025a`, `business-2026s`, `business-2026a`
- `cs-2025a`, `cs-2026s`, `cs-2026a`
- `civil-2026a`, `civil-engineering-2026s`

These are **program offerings**, not necessarily canonical degree programs. No cohort year or entry year is supplied, so none has been inferred.

### Courses by semester

**2026 Autumn — 5 labels**
- Advanced Mathematics (A) 1
- Chinese Language
- Introduction to the Major
- Introduction to the Major (Group 1)
- Introduction to the Major (Group 2)

**2026 Spring — 12 labels**
- Architectural Mechanics (International)
- Chinese, Major 1-2 (International)
- Civil Engineering Drawing (International)
- Digital Electronic Technology
- Discrete Mathematics (International)
- Fundamentals of Programming (International)
- Human Resource Management (International)
- MATHS (A2) (International)
- Management (International)
- Prompt Engineering (International)
- Python Programming (International)
- University Physics A 1 (International)

**2025 Autumn — 11 labels**
- AI Ethics (International)
- AI Thinking and Ethics (International)
- Business and Technology (International)
- Chinese, Major 2-1 (International)
- Computer Organization Principles (International)
- Data Structures and Algorithms (International)
- Fundamentals of Electronic Technology (International)
- Human Resource Management (International)
- Microeconomics (International)
- Organizational Behavior (International)
- Prompt Engineering (International)

Across semesters there are **26 distinct labels**: 28 semester-course assignments with `Human Resource Management (International)` and `Prompt Engineering (International)` repeating.

No Chinese course names are supplied. Only program names have `nameCN`.

### Rooms

`N103`, `N104`, `N105`, `N106`, `N107`, `N301`, `N302`, `G309`, `G310`, `G315`, `G410` — all on the Main campus. No room capacities are supplied.

### Derived sections

The source does not supply section codes. Grouping sessions by semester, course label and the exact set of participating program offerings produces **33 candidate sections**. This is a proposed derivation, not an official section list.

Examples:

- 2026 Autumn `Chinese Language` has three candidate sections: elementary-only, intermediate-only, and one shared by AI, Business, Civil and CS.
- 2026 Autumn `Introduction to the Major` is separate for AI, Civil and Business; CS uses the separately named Group 1 and Group 2 labels.
- 2026 Spring shared courses form one candidate section linked to multiple offerings.

These group labels require approval before section records are created.

---

## 4. Live database inventory

### Current records

| Entity | Current data |
|---|---|
| Periods | `2026-FALL` (Fall 2026, ACTIVE); `VFY1` (Verify Period, 2032, PLANNED) |
| Majors | `CS`, `BUS`, `ENG`, `english` (Artificial Intelligence, orphan) |
| Programs | `BCS` Computer Science; `BBA` Business Administration; `BAL` English |
| Courses | `CS101`, `CS201`, `CS301`, `BA101`, `BA201`, `EN101`, `EN201` |
| Classrooms | `B18-301`, `B18-302`, `B18-401`, `B19-201`, `B19-202` |
| Sections | `CS101-A`, `CS101-B`, `CS201-A`, `BA101-A`, `EN101-A` |
| Timetable | 6 active entries, 0 deleted |

### Database integrity concerns

- `VFY1` is a 2032 verification period, not a source semester.
- `english` is an orphan major holding “Artificial Intelligence” with no program.
- `ENG`/`BAL` describe English, which is not in this Chinese/international reference.
- The current 7 courses, 5 rooms, 5 sections and 6 timetable entries have **no exact match** in the source.
- Current dashboard timetable loading does not filter by semester, so records from more than one period would be mixed in one grid.
- The student academic overview selects the first ACTIVE period but includes all enrolled classes and timetable entries, not only that period.

---

## 5. Missing, conflicting and unmapped records

### Missing

| Category | Missing from portal |
|---|---|
| Semesters | `2026-spring`, `2025-autumn`; `2026-autumn` has only a candidate match to `2026-FALL` |
| Program names | Artificial Intelligence, Chinese Language (Elementary Level), Chinese Language (Intermediate Level), Civil Engineering, Chinese Language and Literature, Robotics Engineering |
| Source course labels | All 26 |
| Source rooms | All 11 |
| Source sections | 33 candidate sections |
| Source sessions | 52 unique weekly sessions |
| Source offering records | 15 (with bilingual names and semester links) |

### Unmapped / legacy live records

- Program: `BAL` (English) — no source match.
- Major: `english` — orphan Artificial Intelligence major, no program.
- All 7 current courses.
- All 5 current classrooms.
- All 5 current class sections.
- All 6 current timetable entries.
- Period: `VFY1`.

No deletion or rewrite is proposed for any of these.

### Conflicts

1. **2026 Autumn format conflict**
   - Source semester declares `standard8`; top-level metadata and actual labels indicate `block4`.
   - Resolution: **block4** for 2026 Autumn, preserving block times above.

2. **Two source room overlaps**
   - 2025 Autumn, Monday, 10:20–12:00, N103:
     `AI Ethics (International)` (AI) vs `AI Thinking and Ethics (International)` (Robotics).
   - 2025 Autumn, Wednesday, 10:20–12:00, N103:
     the same two courses.
   - These have different course names, so they cannot be merged automatically. They may represent a combined lecture or equivalent courses for two cohorts; source data does not say.

3. **Nine shared-session groups**
   - 2025 Autumn: `Chinese, Major 2-1` (4 programs); `Prompt Engineering` (AI + Robotics).
   - 2026 Spring: `Chinese, Major 1-2` (4 programs); `University Physics A 1` (3 programs); `MATHS (A2)` (4 programs).
   - 2026 Autumn: `Chinese Language` (4 programs); `Advanced Mathematics (A) 1` (4 programs).
   - These should become one shared class section linked to multiple program offerings, otherwise the same room/time is booked multiple times.

4. **No program-time conflicts**
   - No program has two different courses overlapping in the same semester and time.

5. **No exact duplicate row within a program**
   - The 24 duplicates are cross-program shared sessions, not accidental repeated rows.

6. **Semester dates are absent**
   - The source supplies no start/end dates.
   - `2026-FALL` has existing dates, but they are not certified by the source.
   - `2026 Spring` and `2025 Autumn` cannot be created under the current non-null date constraints without supplied dates.

7. **Missing official identifiers and attributes**
   - No course codes.
   - No course Chinese names.
   - No section codes.
   - No teachers.
   - No credits.
   - No classroom capacities.
   - No cohort year.
   - No per-session week ranges (only the semester’s weekly pattern).

---

## 6. Field mapping

| Source field | Current storage | Result |
|---|---|---|
| `metadata.*` | none | Import metadata only |
| `timeSlotFormats.*` | none | Missing; needs reference tables |
| `semesters[].id` | no external ID | Missing |
| `semesters[].name` | `academic_periods.name` | Candidate only |
| `semesters[].nameCN` | no column | Missing |
| `semesters[].timeSlotFormat` | no column | Conflicting for 2026 Autumn |
| `programs[].id` | no external ID | Missing |
| `programs[].name` / `nameCN` | `programs.name` only | Chinese name missing; offering dimension missing |
| `schedule[].day` | `timetable_entries.day_of_week` | Map day names to 0–6 |
| `schedule[].session` | no column | Missing; only raw start/end are stored |
| `schedule[].course` | `courses.name` | Code and Chinese name missing |
| `schedule[].location` | `classrooms.room_code` | Room code can map; campus/capacity missing |
| `locations[].building/room/campus` | `classrooms.building/room_code` | Campus missing; capacity absent |
| No source date range | `academic_periods.start_date/end_date` | Source incomplete |
| No source section code | `class_sections.section_code` required | Cannot create honestly without a decision |
| No source course code | `courses.code` required and unique | Cannot create honestly without a decision |

---

## 7. Minimum proposed schema changes

These are **proposals only**; none has been applied.

### A. Import and provenance

- `academic_import_batches` — source hash, status, totals, dry-run result.
- `academic_import_rows` — staged raw rows, validation state, conflict reason, target entity.
- Add `source_key` / source hash columns to imported academic tables for idempotency and rollback.

### B. Timetable formats

- `timetable_formats` — `standard8`, `block4`, descriptions.
- `timetable_slots` — format, label, start/end time, period of day.
- `academic_periods.timetable_format_code` — nullable foreign key, resolved to `block4` for 2026 Autumn.

### C. Semester-specific offerings

- `program_offerings`:
  - `academic_period_id`
  - optional `program_id`
  - `source_id` unique
  - `name`, `name_zh`
  - `timetable_format_code`
  - source hash
- This preserves all 15 source offerings without inventing a parent major for each one.
- Existing `programs` remain the canonical program table.

### D. Courses and bilingual names

- Add nullable `courses.name_zh`.
- Add `courses.source_key`.
- To avoid inventing course codes, either:
  1. make `courses.code` nullable and display the source course name; or
  2. keep `code` required and stage reference courses separately until official codes are supplied.
- Option 1 is the smaller change, but it alters a current non-null constraint. It requires explicit approval.

### E. Sections and shared delivery

- Add `class_sections.source_key`.
- Add `class_sections.source_label`.
- Add `class_section_program_offerings` join table so one shared section can serve multiple program offerings.
- Section code remains unresolved. The source supplies none; making `section_code` nullable is the honest option unless an official scheme is provided.

### F. Sessions

- Add `timetable_entries.slot_label` (e.g. `5-8`).
- Add `timetable_entries.format_code` or resolve it from the period.
- Add `timetable_entries.source_key`.
- Add a partial unique constraint for non-deleted entries:
  `(class_section_id, day_of_week, start_time, end_time, classroom_id)`.
- Add optional `start_week` / `end_week` only if the institution supplies them; the source currently has no week ranges.

### G. Rooms

- Add `classrooms.campus`.
- Add `classrooms.source_key`.
- Allow `capacity` to be null, because the source supplies no capacities.
- Existing rooms remain untouched.

### H. API and UI follow-up (not schema)

- Add semester selector to the academic dashboard instead of loading all periods.
- Add filters by `period_id`, `program_offering_id`, `course_id`.
- Make student timetable retrieval period-scoped by default.
- Render a defined format grid from `timetable_slots`, not a hardcoded set of rows.
- Preserve existing permissions and management dialogs.

No changes are proposed to enrollment, attendance, assessment, grade or change-history tables.

---

## 8. Safe import strategy after approval

1. Run a new backup and record current counts.
2. Re-run the dry run against the approved source hash.
3. Create missing periods only after dates are supplied or approved.
4. Create the 15 program offerings and map only approved parent programs.
5. Create 11 rooms and 26 source course records without inventing codes or capacities.
6. Create candidate sections; link shared sections to multiple program offerings.
7. Create 52 unique sessions with resolved block4/standard8 times and raw slot labels.
8. Leave all existing sections, timetable entries and 24 enrollments untouched.
9. Apply everything in one transaction with per-batch rollback.
10. Verify source/session counts, semester isolation, program/course filters and real student timetable retrieval before closing the batch.

---

## 9. Decisions required before any live write

1. Approve **block4 for 2026 Autumn**.
2. Supply start/end dates for 2025 Autumn and 2026 Spring, and confirm whether `2026-FALL` is the official 2026 Autumn period.
3. Approve parent-program mapping for Business Administration → BBA, Computer Science and Technology → BCS, and what to do with the orphan AI major and legacy `BAL`.
4. Approve creating the six missing program names from the source.
5. Approve the shared-section rule (one section linked to multiple program offerings).
6. Resolve the two 2025 Autumn N103 overlaps between AI Ethics and AI Thinking and Ethics.
7. Confirm how `Introduction to the Major (Group 1)` and `(Group 2)` should be represented.
8. Approve nullable course codes and section codes, or provide official codes.
9. Approve nullable classroom capacity, or provide capacities.
10. Provide Chinese course names; they are absent from the source.

**No live academic-data changes have been made.**
