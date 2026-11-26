# SYCUMAIN V3 — Functional Investigation 01: Institutional Timetable Comparison

**Status:** investigation only. No application code was changed, no data was written or deleted, nothing was migrated, committed, pushed or deployed. Evidence files were added under `docs/evidence/timetable-comparison/` and this report.
**Reference:** <https://sycu-timetable.vercel.app/> (inspected in a real browser on 2026-11-25/26)
**V3 baseline:** `main` @ `8467300`, dev stack `school-portal-v2-{web,api,db}` on `3101 / 8001 / 5435`, database `school_portal_v2` at Alembic `d1e4a7b9c2f5`.
**Evidence tags used:** **VERIFIED** (observed directly, with command/response or browser output), **NOT VERIFIED** (not exercised), **ESTIMATED**, **INSTITUTIONAL DECISION REQUIRED**.

---

## 1. Summary of the institutional reference's observed functionality

The reference is a **published student timetable viewer**, not an academic management system. It serves one read-only artefact: the SCU professional-course timetable for 2026-2027-1, as three semester-specific tables of program→weekly-pattern schedules.

### 1.1 What the browser actually shows

| Element | Observed behaviour | Tag |
|---|---|---|
| Header | `SYCU Timetable — Course schedule for students`, live local clock (`Thursday 5:22 AM`), `Administration` button, colour-theme toggle | VERIFIED |
| Semester selection | Three segmented buttons with the number of programs in each: `2026 Autumn 6`, `2026 Spring 5`, `2025 Autumn 4`. Selecting one re-renders the program list and the schedule area | VERIFIED |
| Program selection | Left rail lists one card per **semester-specific program offering**, bilingual (English + Chinese), with two counters, e.g. `Artificial Intelligence (International) 1 / 人工智能（国际）1 / 4 slots / 8 sessions` | VERIFIED |
| Selected program header | Program name (EN), then `Chinese name · <semester>（<Chinese semester>）`, a program badge with its own slot count, and a `Grid / List` switch | VERIFIED |
| Course legend | Coloured dots/names for every course in the program (`Chinese Language`, `Introduction to the Major`, `Advanced Mathematics 1`) | VERIFIED |
| Grid view | Day columns **only for days that have classes** (AI 2026 Autumn: Monday, Wednesday, Thursday), rows built from the institution's 8-session bell pattern including the breaks (`BREAK 9:05–9:15`, `20 MIN BREAK 10:00–10:20`, `LUNCH 12:00–13:30`), grouped `MORNING 8:20–12:00` / `AFTERNOON 13:30–17:00` | VERIFIED |
| Session card | Course, **session-range label** (`Session 5-8`), resolved time (`13:30-17:00`), **room badge** (`G310`), and an `↑ NEXT` marker on the next upcoming session | VERIFIED |
| List view | Per-day groups with a class count (`Monday · 1 class`), one row per session: slot label (`1-2`), time, course, room badge, `NEXT` chip, `Thursday · today` label | VERIFIED |
| Personal identification | None. There is no login, no student record, no enrollment, no group/class selection. A student finds their timetable by **picking their semester and their program** | VERIFIED |
| Search | One search box: `Search courses, rooms, programs…` (filters the program rail) | VERIFIED |
| Footer | `2026-2027-1 专业课表 · generated 2026-10-09 · updated 2026-10-23 09:26 · Asia/Shanghai` and `3 semesters · 15 programs · 76 classes` | VERIFIED |
| "Now" strip | `Local time 5:22 AM · Thursday · ↑ Next: Advanced Mathematics (A) 1 @ G310` | VERIFIED |
| Mobile / responsive | At 390 px (emulated) the program rail stacks **above** the schedule: semester chips → search → six program cards → then the selected program's heading and grid. The day-grid is horizontally scrollable; there is no day selector and no "today" shortcut. Reaching the actual schedule requires scrolling past the whole rail | VERIFIED |
| Administration | A login modal is wired to the `Administration` button. Clicking it produced **no visible panel** in two attempts; the modal markup exists in the DOM but stayed collapsed. The module itself is shipped at `/admin.js` | VERIFIED (limited, see §11) |

### 1.2 The reference data contract

The page is fed by `GET /api/timetable`, observed from the browser:

```text
metadata:      source, generated, timezone (Asia/Shanghai), totalSemesters 3, totalPrograms 15, updated
timeSlotFormats: standard8 { slots: 1..8 → time, period(morning|afternoon) }
                 block4    { slots: "1-2","3-4","5-6","7-8" → time, period }
semesters[3]:  { id, name, nameCN, timeSlotFormat, programs[] }
programs[]:    { id, name, nameCN, schedule[] }
schedule[]:    { day: "Monday".."Friday", session: "1-2"|"3-4"|"5-8"…, course: <name>, location: <room code> }
locations[]:   rooms
```

Observed totals: **15 offerings, 76 schedule rows, 11 rooms, 2 slot formats**. There is **no teacher, no class/section, no capacity, no student, no enrollment, no date range and no week range** anywhere in the payload. `2026 Autumn` declares `standard8` in the payload while the top-level description and its actual labels (`1-2`, `5-8` only) indicate `block4`; the app renders from the label → time map, so this inconsistency is invisible to the student (VERIFIED payload, VERIFIED rendering).

### 1.3 The reference administration module

The browser loaded `admin.js` (39,325 bytes). Its own header comment states: *"Login-gated editing of the timetable data (semesters, programs, classes, rooms). Edits persist in localStorage and can be exported back to data/timetable.js for publishing."* Observed in the shipped module (VERIFIED as source shipped to the browser; the panel itself was **not** entered):

* A single fixed administration identity whose **salted SHA-256 digest and salt are shipped in the file**, with a documented demo credential in the source comment.
* 8-hour session in `localStorage`, 5-failure / 30-second lockout.
* Editor tabs: **Semesters**, **Programs & classes**, **Rooms**; `Save changes` / `Discard`.
* Persistence: `localStorage` first, then an optional publishing token from `POST /api/login`; `Export` produces `data/timetable.js` for redeployment. Messages shown in its DOM include `Imported on this device only — not published`, `Imported and published — live for everyone`, and `Saved changes go live for every visitor immediately. If the server is unreachable, edits stay on this device and can be published with Export`.
* Import is a client-side file import; there is no audit trail, no role separation, no draft review, no approval.

This is a demo-grade publishing tool. It is materially weaker than V3's server-side, audited, RBAC-controlled academic configuration (see §7).

---

## 2. V3 timetable architecture and data relationships

### 2.1 The implemented chain

```text
Student
  └─ AcademicAdmission (ACTIVE > ADMITTED > COMPLETED/WITHDRAWN; PENDING/CANCELLED excluded)
       └─ AcademicPlacement (ended_at IS NULL)  ── program_offering_id ──►  ProgramOffering
                                                                              ├─ academic_period_id ─► AcademicPeriod
                                                                              └─ program_id ─► Program ─► Major
ClassSection (course_id, academic_period_id, section_code/source_label, capacity, status)
  ├─ ClassSectionProgramOffering (M:N)  ──► ProgramOffering     (one section can serve several offerings)
  ├─ TeacherAssignment (staff_id, is_active)                     (teacher visibility scope)
  ├─ Enrollment (student_id, status ENROLLED/DROPPED/COMPLETED)
  └─ TimetableEntry (classroom_id, day_of_week 0=Mon..6=Sun, start_time, end_time,
                     slot_label, is_deleted)
        └─ Classroom (room_code, building, capacity, status)
```

**Key structural property (VERIFIED in models and schema):** a `timetable_entries` row has **no `academic_period_id`**. Its period is its section's period. A mixed-period grid is therefore impossible by construction; only the API filter chooses which period is shown. This is the correct answer to the old "timetable belongs to a program" assumption: a schedule belongs to a **section inside a period**, and a section belongs to one or more **program offerings of that period**.

### 2.2 Where each piece is implemented

| Concern | Location | Notes |
|---|---|---|
| Student→program resolution | `apps/api/app/services/student_academic.py` | `EFFECTIVE_ADMISSION_STATUSES` excludes PENDING/CANCELLED; `current_placement()` requires a live admission; `student_academic_snapshot()` returns admission, placement, program, major, offering |
| Visible sections | `apps/api/app/services/academic.py::get_student_visible_class_section_ids` | Offering sections when a placement exists (and its period matches the request), else enrollment fallback |
| Student timetable | `academic.py::get_student_timetable` / `get_student_academic_overview` | Offering ∪ enrollments, then **intersect** with actual enrollments when any exist |
| Staff timetable | `academic.py::list_timetable_entries` | Filters `period_id`, `class_section_id`, `course_id`, `program_offering_id`; excludes soft-deleted by default |
| Write rules | `academic.py::_validate_timetable_slot` | Invalid interval, missing section, unusable room, and **three overlap rules** (section, classroom, teacher) under a transaction lock |
| Source catalog view | `apps/api/app/services/source_intakes.py` | Reads `docs/scu-timetable-domain-map.json`, joins by `academic_periods.source_key = ref:v1:period:<id>` and `program_offerings.source_key = ref:v1:offering:<id>` |
| Canonical import | `apps/api/app/services/academic_import.py` | `prepare_import` / `apply_import` / `rollback_batch`, batch tables; **the only writer of `ref:v1:*` keys** |
| Intake planning | `apps/api/app/services/intake_plan.py` | Creates periods + offerings only, idempotent, conflict-reporting; keys `intake:<code>:<source_id>` |
| Seed-key offerings | DB rows `BAL/BBA/BCS` | `source_key = seed:2026-FALL:<code>` |
| Frontend pages | `app/[locale]/(protected)/app/academics/page.tsx` (1,043 lines), `.../academics/calendar/page.tsx`, `.../students/[id]/page.tsx?tab=timetable`, `components/academics/weekly-timetable.tsx`, `.../timetable-editor.tsx` | Weekly grid is data-driven from distinct start times; mobile switches to a day selector |
| Student home | `components/dashboard/student-dashboard.tsx` + `lib/student-dashboard.ts` | Next class, class-day calendar, upcoming sessions, all derived from the same entries and the period's dates |

### 2.3 Role scoping in the API

`_visible_class_section_ids()` is the single gate: ADMIN/MANAGEMENT → `None` (unrestricted); TEACHER → active `teacher_assignments`; STUDENT → own offering∩enrollments; anything else → empty set. `_check_student_scope()` additionally rejects a student reading another student, and a teacher reading a student they do not teach. Verified by API (§6).

---

## 3. Screenshots and reproducible evidence

All images are in `docs/evidence/timetable-comparison/`.

| File | What it shows |
|---|---|
| `01-reference-grid.png` | Reference, 2026 Autumn / Artificial Intelligence, **Grid**: bell-period rows, room badges, `Session 5-8`, `↑ NEXT`, bilingual header |
| `02-reference-list.png` | Reference, same program, **List**: per-day grouping with class counts, slot labels, room badges, `NEXT` chip |
| `03-reference-mobile.png` | Reference at 390 px: segment chips → search → program rail stacked above the schedule (schedule pushed off the first screen) |
| `05-v3-student-timetable-mobile.png` | V3 student timetable at panel width <768 px: Mon/Tue/Wed/Thu/Fri day selector with per-day counts and `No classes are scheduled for this day` for Thursday |
| `07-v3-academics-timetable-empty.png` | V3 Academics: `Classes` card "Official academic-period configuration is pending…" and `Timetable` card "No timetable has been imported for this intake because its official academic period is not configured." |
| `08-v3-student-timetable-ar-rtl.png` | V3 student timetable in **Arabic**: `dir=rtl`, mirrored grid (time column on the right, Monday rightmost), translated labels |
| `09-v3-student-desktop-grid.png` | V3 student timetable desktop: `TIME` + Monday…Friday columns, one row `09:00`, CS101 · A cards on Mon/Wed/Fri |

The two systems were captured from the same browser session against the live reference and the local V3 dev stack; no mock-ups were produced.

---

## 4. Exact reproduction of the reported issue

> "The active V3 timetable contains details, including the program, but does not appear to show the timetable properly, or the expected timetable view is not obvious."

### 4.1 Reproduced: institutional Academics page shows program detail and no schedule

1. Sign in as `admin@school.portal` (ADMIN).
2. Open `/en/app/academics`.
3. Observe the header badge and readiness panel: **Source intake `2026 Autumn`**, `Identified`, **Academic period: Not configured**, **Timetable data: Not imported**, **Readiness: Not ready**; counters `Program offerings 6`, `Programs 3`, `Courses 7`, **`Classes —`**, **`Timetable —`**.
4. The `Program offerings` card is populated with the six 2026 Autumn source offerings (e.g. `Artificial Intelligence (International) 1 · ai-2026a · 3 subjects · 2 shared sections`) and their subjects — this is the "program details" that *are* visible.
5. Scroll to `Classes`: *"Official academic-period configuration is pending. No classes or student assignments are available for this intake."*
6. Scroll to `Timetable`: *"No timetable has been imported for this intake because its official academic period is not configured."*
7. Switch the `Source intake` selector to `2026 Spring` and `2025 Autumn`: identical result. **No selection in the selector is a configured intake**, so no selection can display the Fall 2026 data that exists in the database.
8. Sign in as `student@school.portal`: `/en/app` shows program, intake `Fall 2026`, next class, class-day calendar and 3 upcoming sessions; `/en/app/students/<id>?tab=timetable` shows a 3-session weekly grid. **The schedule exists and renders — but only on the student/staff-scoped screens, not on the intake view.**

This is deterministic. It is not a rendering bug: `loadAcademicBundle()` selects `intakes.find(active) ?? intakes[0]`, and every catalog intake reports `period = null`.

### 4.2 Reproduced: the schedule is incomplete for the student

`STU-001` is enrolled in **3** sections (`CS101-A`, `CS101-B`, `CS201-A`) but the timetable contains **3 sessions, all `CS101-A`**, because `CS101-B` and `CS201-A` have **zero** timetable rows (`EN101-A` too). The dashboard still says "3 enrolled classes" and the timetable card says "3 sessions", so the counts agree while the coverage does not. The platform's own reconciliation endpoint flags exactly this (`SECTION_WITHOUT_TIMETABLE`, 3 items) and `SECTION_WITHOUT_TEACHER` (3 items), status `REVIEW`.

### 4.3 Not reproduced (checked, behaving correctly)

* No period mixing: the grid is scoped by `period_id`, and an entry's period is its section's period.
* No cross-offering leakage: a student's visible sections come from their own placement offering (shared sections do not widen scope).
* No cross-student access: `GET /academics/students/<other>/timetable` → **403** for a student.
* No future-admission leakage: PENDING/CANCELLED admissions never participate in the snapshot.
* No history overwrite: soft delete + audit; historical reads accept a `period_id` and fall back to that period's enrollments.

---

## 5. API and database evidence

All commands were run against the live dev stack; cookies are the real login sessions of the four demo roles.

### 5.1 Source-intake catalog (ADMIN)

```http
GET /api/v1/academics/source-intakes
200
2026-autumn | period: null | configured: false | imported: false | offerings: 6 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
2026-spring | period: null | configured: false | imported: false | offerings: 5 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
2025-autumn | period: null | configured: false | imported: false | offerings: 4 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
```

**Every intake is unconfigured.** This is the whole first screen of the Academics page.

### 5.2 Database state (read-only queries)

```text
academic_periods: 2026-FALL  Fall 2026    ACTIVE  2026-09-01..2026-12-20  source_key NULL
                  2026S      2026 spring  ACTIVE  2026-03-28..2029-03-30  source_key NULL

program_offerings: BAL Bachelor of Arts in English         2026-FALL  source_key seed:2026-FALL:BAL
                   BBA Bachelor of Business Administration  2026-FALL  source_key seed:2026-FALL:BBA
                   BCS Bachelor of Computer Science         2026-FALL  source_key seed:2026-FALL:BCS

class_sections (5): CS101-A (3 sessions), BA101-A (2 sessions),
                    EN101-A (0), CS201-A (0), CS101-B (0)
class_section_program_offerings: 5 links (BCS×3, BBA×1, BAL×1)
timetable_entries: 5 live, 0 deleted
students 28 · academic_admissions 27 (25 ACTIVE, 1 COMPLETED, 1 WITHDRAWN) · placements 25 (all open)
enrollments 51
```

Two facts follow directly:

1. **No period carries a `ref:v1:period:*` key**, so the catalog cannot resolve any intake to a period.
2. **No offering carries a `ref:v1:offering:*` key**, so even a resolved period would report every offering as `SOURCE_ONLY`.

### 5.3 The scaffolded data is nonetheless consistent (ADMIN)

```http
GET /api/v1/academics/program-offerings?period_id=<2026-FALL>
BAL selectable=true · BBA selectable=true · BCS selectable=true

GET /api/v1/academics/classes?period_id=<2026-FALL>&page_size=100
total 5
CS101 A offerings=[BCS] teachers=[User]
CS201 A offerings=[BCS] teachers=[]
BA101 A offerings=[BBA] teachers=[User]
EN101 A offerings=[BAL] teachers=[]
CS101 B offerings=[BCS] teachers=[]

GET /api/v1/academics/timetable?period_id=<2026-FALL>
entries 5 · Counter({'CS101': 3, 'BA101': 2})
```

### 5.4 The platform's own integrity report (ADMIN)

```http
GET /api/v1/academics/timetable/reconciliation?period_id=<2026-FALL>
status REVIEW · periods 1 · sections 5 · live_entries 5 · retired 0
findings 6 · blocking 0 · warnings 6
  SECTION_WITHOUT_TEACHER  ×3  (CS101-B, CS201-A, EN101-A)
  SECTION_WITHOUT_TIMETABLE ×3 (CS101-B, CS201-A, EN101-A)
```

The diagnostic already exists and already knows the data is incomplete; the timetable card does not display it.

### 5.5 Student resolution (STUDENT session)

```http
GET /api/v1/academics/students/9d4cf33a-…-7a5c31e0ea8a
program: Bachelor of Computer Science | offering: Bachelor of Computer Science
current_period: 2026-FALL | selected: 2026-FALL | is_current: true
classes: CS201-A, CS101-B, CS101-A  (Fall 2026)
timetable: 3 entries — Mon/Wed/Fri 09:00–10:00 CS101-A B18-301, teacher "Teacher User"
```

`is_current` is true and the period is correct: the student half of the chain resolves properly. The failure is upstream, in the intake/period configuration, and in the completeness of the section data.

### 5.6 The two incompatible source-key contracts (root cause R2)

| Producer | Period key | Offering key |
|---|---|---|
| `academic_import.py` (reader expects these) | `ref:v1:period:<source_id>` | `ref:v1:offering:<source_id>` |
| `source_intakes.py` (looks up exactly these) | `ref:v1:period:*` | `ref:v1:offering:*` |
| `intake_plan.py` (`POST /academics/intakes/plan`) | **period `source_key` never set** | `intake:<period_code>:<source_id>` |
| Seed (`seed_demo_full`) | `NULL` | `seed:<period>:<code>` |
| Manual `POST /academics/program-offerings` | n/a | `manual:<period_id>:<source_id>` |

Only the first row satisfies the reader, and `academic_import` has **no router, no CLI entry and no UI** (grep across `apps/api/app/routers`, `apps/api/tools`, `scripts` returns no caller). Consequently:

> There is currently **no supported write path** — UI or API — that makes a source intake appear `configured` in the Academics page.

That is the architectural defect behind the symptom, not a CSS or component bug.

---

## 6. Role-by-role behaviour

All four accounts are the seeded demo roles; each was signed in over HTTP, and ADMIN/STUDENT were also exercised in the browser.

| Role | Academics page | Timetable data reachable | Student timetable | Notes |
|---|---|---|---|---|
| **ADMIN** | Opens; intake selector (3 source intakes), program offerings, periods, courses, classrooms, classes, timetable cards | Fall 2026: 5 sections, 5 entries. Source intakes: none. Cannot configure an intake from the UI | Any student, any period | Sees `Classes —`/`Timetable —` on the default intake even though the period data exists |
| **MANAGEMENT** | Same page, same permissions for academic configuration (`academic.manage_*` present) | `GET /academics/timetable` → 5 entries (unrestricted) | Any student | Indistinguishable from ADMIN in this area |
| **TEACHER** | Opens (`academic.view`); no manage actions | `GET /academics/classes` → 2 (only assigned sections); `GET /academics/timetable` → 5 entries, all from their 2 sections | Only students they teach; otherwise 403 | Scoping works exactly as specified |
| **STUDENT** | **Opens when navigated directly** (route guard is `academic.view`, which students hold) although the nav hides it | Sees the institutional curriculum: programs, all 7 courses, all 5 classrooms, both periods, the source-offering catalog | Own timetable only: 3 sessions; another student → **403** | Inconsistent: `hiddenForRoles: ["STUDENT"]` in nav, but the page-level "student scope" empty state is unreachable because students pass `hasPermission("academic.view")` |

Student home (`/app`) is a genuinely student-shaped timetable view: program + intake, next class with room/teacher, a class-day calendar bounded by the period's start/end, upcoming sessions, examinations. It is the strongest student-facing piece of the current implementation.

---

## 7. Comparison matrix

Legend: **✔ works** · **◐ exists but incorrect / incomplete** · **◑ exists but hard to discover** · **✘ missing** · **— not applicable to the reference**

| Capability | Institutional reference | V3 current behaviour | Gap |
|---|---|---|---|
| **Student timetable** | Pick semester → pick program → weekly grid/list. No identity, no enrollment, no "my" timetable | Student home + `Timetable` tab give a personal weekly grid from enrollments∩offering, with room, teacher, next class, calendar | V3 is stronger in principle (personal, periodic, authorized). **◐** in practice: only 1 of 3 enrolled courses has sessions; the personal timetable is not in the navigation |
| **Program selection** | Primary interaction: 6 / 5 / 4 offering cards per semester, bilingual, with slot/session counts | `Source intake` → `Program offering` filter on the Academics page; offering names are English-only there (Chinese name exists in the payload but is not rendered) | **◑** Program-level timetable exists but is reachable only by filtering a whole-period grid; no per-program page |
| **Intake / semester selection** | Three semester buttons, always populated, always consistent with the data shown | Selector lists the three **source-catalog** intakes; none is mapped to a period, so every one shows an empty schedule. The periods that *do* hold data (`Fall 2026`, `2026 spring`) are not in the selector | **◐** Critical: the selector does not select the data |
| **Course display** | Course name only, plus colour legend, per-program | Course code + section + name + slot label + time, colour per course | **✔** Richer; but the whole-period grid shows every course mixed together unless the offering filter is used |
| **Day / time scheduling** | Fixed institutional bell pattern (8 sessions + named breaks), explicit `MORNING`/`AFTERNOON`, session-range labels (`5-8`), `↑ NEXT` | Rows are built from **distinct start times in the data**, so 5 sessions on 3 different hours become 1 row etc.; no bell pattern, no breaks, no slot labels unless the importer stored `slot_label` (null in the current data), no `NEXT` marker | **◐** Functional but less informative; an institutional period vocabulary is missing |
| **Classroom display** | Room badge in every card, `locations[]` in payload | Room code in card; classroom table with capacity and availability in the admin area | **✔** |
| **Teacher information** | **None** (not in payload) | Teacher names per section, teacher assignment admin, teacher-scoped visibility | **✔** V3 exceeds the reference |
| **Search / filtering** | Global search over courses, rooms, programs | Search exists on classes/programs API (`search=`) but **no search control on the timetable**; filters are intake/offering/course only | **✘/◑** Timetable search missing; filters present |
| **Administrative management** | Client-side editor (semesters / programs & classes / rooms), localStorage, one shipped credential, no audit, no roles | Server-side CRUD with RBAC, audit, soft delete, overlap validation, class history, teacher assignment | **✔** V3 substantially stronger — except that intake configuration and canonical import are not exposed at all (**◐** on the operational path) |
| **Publishing changes** | Explicit `Export` → `data/timetable.js`; localStorage staging; "live for every visitor immediately" when a token exists | No draft/publish step: an authorised edit is live on the next request; audit row records it | **✘** for publish/approval; may be acceptable (INSTITUTIONAL DECISION REQUIRED) |
| **Import / export** | Client-side import; export to a JS data file | `prepare_import` / `apply_import` / `rollback_batch` service + batch tables exist, **unexposed**; no timetable export (CSV/ICS/print) | **✘** in the UI; the machinery exists server-side |
| **Mobile usability** | Rail stacks above the schedule; grid scrolls horizontally; no day selector | Day-selector + agenda replaces the grid below 768 px, with per-day counts and empty state | **✔** V3 better on mobile; reference is barely usable on a phone |
| **Localization** | English + Chinese program/semester names only; UI strings English | 5 locales (en, zh, fr, ru, ar) for all timetable strings; Arabic RTL mirrored grid, verified | **✔** V3 exceeds the reference |
| **Responsiveness of "what do I have next"** | `↑ Next:` strip; `NEXT` chip in both views | Next class card, upcoming list, class-day calendar, "next" tag on today's column | **✔** comparable/stronger |

### Classification summary

* **Works**: server-side timetable CRUD + conflicts; per-role scoping; student personal timetable rendering; classroom and teacher data; Arabic RTL; mobile agenda; audit and soft delete; period isolation.
* **Works incorrectly**: the Academics intake selector (selects a catalog, not data); the intake→period/offering key contract; readiness/coverage reporting not surfaced where the timetable is shown.
* **Works but is hard to discover**: the timetable itself (6th card on a 1,043-line page, no nav entry, no per-program view); the per-offering filter; the student timetable (one click from the dashboard, not in the nav).
* **Genuinely missing**: intake configuration from the UI; canonical import/apply; per-program timetable page; publish/approval; timetable search; export/print/ICS; slot-period vocabulary; coverage warnings in the timetable card.

---

## 8. Root causes, ranked by severity

### R1 — The Academics page is catalog-first, so it opens on an intake that can never contain data · **CRITICAL**

`loadAcademicBundle()` calls `listSourceIntakes()` and picks `intakes.find(active) ?? intakes[0]`. All three catalog intakes report `period_configured: false`, so `selectedPeriodId` is `null`; classes, timetable and offerings lists are then replaced with empty arrays and the counters render `—`. The page is *working as coded* and simultaneously incapable of showing the period data that exists.

Evidence: §5.1, §5.2, §4.1, screenshot `07`.
Consequence: the very first screen an administrator sees for "Academics" contains program narrative and no schedule, which is exactly the reported observation.

### R2 — No supported write path links the accepted source timetable to V3's period/offering model · **CRITICAL**

`source_intakes.py` requires `ref:v1:period:<id>` / `ref:v1:offering:<id>`; `academic_import.py` is the only producer of those keys and is not exposed by any router, CLI or screen; `intake_plan.py` writes `intake:<code>:<id>` and never sets the period's `source_key`; manual offering creation writes `manual:*`; the seed writes `seed:*`. Four naming conventions, one accepted by the reader, none reachable from the product.

Consequence: even the correct administrative action (`POST /academics/intakes/plan`, which *is* exposed) cannot make an intake `configured`. The data path is broken at the seam, not at any single screen.

### R3 — Timetable coverage is incomplete and the incompleteness is not shown where it matters · **HIGH**

3 of 5 sections have no sessions; 3 have no teacher. A student enrolled in three courses sees one course. The reconciliation endpoint reports it (`REVIEW`, 6 warnings) but the timetable card shows nothing; it only renders an empty state when the *whole list* is empty. Section cards do show an "unassigned" badge for teachers, so the pattern exists — it is simply not applied to sessions.

### R4 — There is no program/offering timetable view, and the timetable is buried · **HIGH**

The reference's primary artefact is "one program's week". V3's equivalent — `period + program_offering_id` filtering — exists in the API and in the page's filter row, but the rendered result is still a period-wide grid with dozens of unrelated sessions; the offering is not in the page title, the grid, or the URL. The card is the sixth of six stacked cards, below 1,800+ px of scroll, with no navigation entry and no link from a student's programme summary.

### R5 — Catalog counters and database counters are mixed on one screen · **MEDIUM**

`Program offerings 6` (catalog) against `Programs 3`, `Courses 7`, `Classes —` (database) in the same grid. A reader reasonably concludes there are six offerings in the system; there are three. `timetable_imported` is `false` not because no rows exist but because no source import exists — the label says "Timetable data: Not imported", while a timetable *is* present.

### R6 — Student access to the institutional curriculum page contradicts the navigation · **MEDIUM**

`navigation.ts` hides Academics from STUDENT; `page.tsx` gates only on `academic.view`, which STUDENT holds; the `studentScopeNotice` branch is therefore dead for students. Verified by direct navigation as a student (§6). This is a read-only institutional view (no personal data, no teacher names beyond what the class cards expose), so the impact is consistency and information disclosure rather than privilege escalation — but the two layers disagree.

### R7 — No publishing / effective-dating model for timetable changes · **MEDIUM** (INSTITUTIONAL DECISION REQUIRED)

The reference has an explicit export/publish act. V3 writes live and audits. There is no "scheduled from date", no draft, no approval, and no schedule-diff view (class history covers assessments/grades). If the institution expects a publication gate for timetable changes, this is a real gap; if "authorised edit is immediately authoritative" is the agreed rule, only the change-history view is missing.

### R8 — Timetable utility features absent · **MEDIUM**

No search, no print, no CSV/ICS export, no week/date navigation on the timetable component, no session-period labels in the grid (`slot_label` is stored but null in current data), no `NEXT` marker in the student grid (the dashboard has one). The reference has search, both views on all breakpoints, slot labels and a next-session marker.

### R9 — Presentation inconsistencies · **LOW**

Student home prints `Bachelor of Computer Science · Bachelor of Computer Science · Computer Science` (program · offering · major, three similar strings); "3 enrolled classes" sits beside a timetable showing one course; the offering card shows English only while the payload carries `name_zh`.

### R10 — Late enrolment has no recorded authorization/reason · **MEDIUM** (business rule)

`EnrollmentCreate` is `{student_id}`; `enroll_student` checks section status and capacity but not the period's dates, and the audit context stores ids/status only. An enrolment into an earlier intake is therefore *possible* but is not accompanied by the authorization and reason the requirements call for. No field, no workflow, no prompt.

---

## 9. Recommended corrections, grouped into implementation tasks

Nothing below is implemented. Each task is independently shippable and preserves the intake-based architecture: **no new timetable model, no program-owned timetable, no change to V1.**

### T1 — Make the Academics page data-first (fixes R1, R5) · Critical · small

1. In `loadAcademicBundle()`, resolve the selector from **periods that exist** (`listPeriods`) joined to their offerings, not from the source catalog. Default to the period whose `status = ACTIVE` and that has offerings; fall back to the newest period with offerings; only then to the catalog.
2. Keep the source catalog as a **separate, clearly labelled** "Source timetable" section (read-only audit), with its own counters — never mixed into the same stat grid.
3. When the catalog intake is shown, label it `Source only — not configured` and link to the configuration action (T2), instead of presenting it as the page's subject.
4. Show `Classes` / `Timetable` counters for the selected period even when it came from the database rather than the catalog.

### T2 — One source-key contract and an exposed, audited configuration/import path (fixes R2) · Critical · medium

1. Choose one canonical key form (`ref:v1:*` is already the reader's contract) and make `intake_plan` and manual creation agree with it, or teach `source_intakes` to accept the planned form. Add `academic_periods.source_key` to `plan_intakes`.
2. Expose `prepare_import` (dry run, staged rows, conflict report), `apply_import` and `rollback_batch` behind `academic.manage_periods` + `academic.manage_timetable`, with an explicit confirmation, batch id and audit rows. A `scripts/` CLI wrapper is the minimum; an admin screen is the complete answer.
3. Add an idempotent "Configure intake from source" action that creates the period (dates supplied by the institution), the offerings, sections, shared-section links and sessions, and reports per-row outcomes; refuse silently-different dates (the existing `CONFLICT` behaviour).
4. Do not auto-create periods from the source's undated semesters (2025 Autumn, 2026 Spring) — dates remain an institutional decision.

### T3 — Surface timetable coverage (fixes R3) · High · small

1. In the timetable card header, show `reconciliation` counts (`N sections without sessions`, `N without teacher`) as a warning, linking to the sections.
2. On each section card, add a "no sessions" badge beside the existing "unassigned" teacher badge.
3. On the student timetable, when a section in `enrolled_classes` has no sessions, list it under the grid as "no scheduled sessions yet" — the student should see the course even when the schedule is missing.

### T4 — Add the program/offering week view (fixes R4, R8 partially) · High · medium

1. Route: `/app/academics/[periodId]/offerings/[offeringId]/timetable` (or a tab on the Academics page) rendering `WeeklyTimetable` for `GET /timetable?period_id=…&program_offering_id=…`.
2. Reuse the existing component; add the offering name + intake name + Chinese name to the header, and a `Grid / List` switch (list = existing mobile agenda on desktop).
3. Add an optional bell-pattern axis when `period.timetable_format_code` is present (block4 / standard8), rendering rows from the format rather than from data start times; keep the data-driven fallback.
4. Render `slot_label` when present (`Session 5-8`), and mark the next session.

### T5 — Navigation and cross-links (fixes R4 discoverability) · Medium · small

1. Add a `Timetable` entry: staff → the period/program view; students → their own timetable.
2. Split the Academics page into tabs (`Intakes`, `Courses`, `Classes`, `Timetable`, `Rooms`) so the schedule is not the sixth scroll panel.
3. Link from the student programme summary ("3 enrolled classes") to the timetable tab.

### T6 — Align the student route guard (fixes R6) · Medium · small (decision)

Either (a) keep students out: require a staff permission (`academic.manage_programs` or a new `academic.view_curriculum`) on `/app/academics`, or (b) allow it deliberately: remove the nav hiding and the dead `studentScopeNotice`, and present a read-only curriculum view. Option (a) matches the current comment in `navigation.ts`.

### T7 — Publication model (fixes R7) · Medium · INSTITUTIONAL DECISION REQUIRED

If a publication gate is required: add `TimetableChangeSet` (draft/approved/published, effective_from) that materialises into `timetable_entries` on publish, plus a schedule-diff view. If not: document that authorised edits are immediately authoritative and add a read-only change-history view over the audit entries (`academic.timetable.*`).

### T8 — Timetable utilities (fixes R8) · Medium · medium

Search within the visible schedule; print stylesheet; CSV/ICS export of the student's or an offering's week; keep ICS UID stable per section+entry id.

### T9 — Late-enrolment authorization (fixes R10) · Medium · INSTITUTIONAL DECISION REQUIRED

Add optional `authorization_reference` and `reason` to `EnrollmentCreate`, require them when the section's period is not the current active one, record them in the audit `changes`, and display them on the class roster. No schema change is needed if the values live in the audit context only; a column is needed if they must be queryable.

### T10 — Presentation cleanup (fixes R9) · Low · small

Deduplicate the programme/offering/major line; render `name_zh` beside offering names where the locale is Chinese; make "N enrolled classes" and "N sessions" visibly distinct.

### Ordering

`T1 → T2 → T3 → T4 → T5` is the safe sequence: T1 makes the screen truthful with existing data, T2 makes real institutional data reachable, T3 makes incompleteness honest, T4 delivers the reference's core artefact, T5 makes it findable. T6–T10 are independent.

---

## 10. Regression tests required for each correction

Backend tests are `pytest` in `apps/api/tests`; frontend has Playwright specs in `apps/web/e2e`.

| Task | Tests |
|---|---|
| **T1** | `test_academics_page_defaults_to_active_period_with_data` (API fixture: catalog unconfigured + one configured period; assert selector resolves the configured period). `test_source_only_intake_is_labelled_and_not_mixed_with_db_counts`. Existing `test_source_intakes*` must keep passing unchanged. |
| **T2** | `test_plan_intakes_sets_period_source_key`; `test_plan_intakes_offering_key_matches_catalog_contract`; `test_source_intake_becomes_configured_after_plan`; `test_import_dry_run_writes_no_target_rows`; `test_import_apply_is_idempotent_and_audited`; `test_import_rollback_removes_only_batch_rows`; `test_import_refuses_conflicting_period_dates`; `test_import_requires_manage_timetable_permission`; `test_import_rejects_n103_conflict_as_held`. |
| **T3** | `test_timetable_card_shows_reconciliation_summary`; `test_section_without_timetable_is_flagged` (the existing `reconcile_timetable` test already asserts the finding — add the UI-facing assertion); `test_student_timetable_lists_enrolled_sections_without_sessions`. |
| **T4** | `test_offering_timetable_returns_only_that_offerings_sections`; `test_shared_section_appears_once_for_two_offerings`; `test_offering_timetable_hides_other_period_entries`; `test_offering_timetable_requires_offering_in_period`; `e2e: offering week renders grid and list with slot labels`. |
| **T5** | `e2e: staff nav reaches timetable; student nav reaches own timetable`; `e2e: academics tabs keep period selection across tabs`. |
| **T6** | `test_student_cannot_read_academics_curriculum` (403/redirect) **or**, for option (b), `test_student_curriculum_is_read_only` (no manage controls, no other cohort's personal data). Must keep `test_student_cannot_access_other_student` green. |
| **T7** | If implemented: `test_draft_change_set_is_not_visible_in_timetable`; `test_publish_materialises_entries_atomically`; `test_historical_entries_survive_republish`. If not: `test_timetable_audit_is_queryable_by_period`. |
| **T8** | `test_timetable_search_matches_course_room_teacher`; `test_ics_export_contains_one_vevent_per_entry_with_stable_uid`; `test_export_respects_role_visibility` (student export contains only own sections). |
| **T9** | `test_late_enrolment_requires_authorization_when_period_not_current`; `test_late_enrolment_records_reason_in_audit`; `test_current_period_enrolment_unchanged`. |
| **T10** | `e2e: student header shows program once`; snapshot-free assertion on the rendered string. |

Cross-cutting invariants that must remain green after every task: `test_audit_immutability`, `test_audit_history`, `test_migration_guard`, the source-intake suite, `test_platform` locale parity, and the RTL/`dir` assertions in the web suite.

---

## 11. Explicitly unverified items and access limitations

1. **Reference administration panel was not entered.** The `Administration` button produced no visible panel in two attempts; both the login dialog and the manager dialog exist in the DOM but stayed collapsed. The capabilities in §1.3 are read from the module the browser loaded and from its DOM labels, **not** from a completed admin session. The demo credential is published in that module, but I did not use it to obtain access, and no institution's account was touched.
2. **The reference's counter semantics** (`3 slots / 8 sessions`) are not published. "Slots" clearly counts distinct weekly placements; "sessions" does not equal the sum of period counts for every program, so its exact rule is NOT VERIFIED.
3. **Reference data is a static snapshot** (`generated 2026-10-09`, `updated 2026-10-23`). Any live change after that date would not be reflected here.
4. **V3 has no imported institutional dataset in the current dev database.** The 2026 Autumn import described in `docs/scu-timetable-reconciliation-report.md` is not present in `school_portal_v2` (no `ref:v1:*` keys, no `academic_import_batches` rows). All V3 statements about rendering are therefore based on the 3 seeded offerings / 5 sections / 5 entries. The behaviour on a fully imported dataset — 15 offerings, 33 sections, 52 sessions — was **not** exercised in this investigation.
5. **Teacher and Management were checked by API, not in the browser** (ADMIN and STUDENT were checked in both). The UI branches for those roles are permission-gated by the same flags verified in `GET /auth/me`.
6. **No automated test was run** for this investigation, because no code was changed. The existing suite's state is taken from the Phase 10 report (1,103 passed, 2 skipped) and was not re-executed.
7. **No build/typecheck was run**; only documentation and PNG evidence were added.
8. **Arabic RTL was verified on the student timetable only** (grid mirroring, `dir=rtl`, translated strings). The admin tables under RTL and the Arabic Academics page were not inspected.
9. **Mobile behaviour** was checked by viewport emulation in Chromium (390 px and ~1050 px panel width), not on physical devices, and not with Safari/iOS.
10. **Accessibility** (keyboard traversal of the grid, screen-reader semantics of the day tabs, contrast) was not audited. The table markup and `aria-selected` tabs look sound but were not tested.
11. **Performance** of the timetable endpoints was not re-measured. `_build_timetable_response` performs per-entry queries (teachers, offerings); with 52 imported sessions this is worth measuring before the full import (ESTIMATED, low risk for one period).
12. **Institutional decisions still open** and out of scope here: official period dates/codes for 2025 Autumn and 2026 Spring; the N103 overlap; Group 1/Group 2 semantics; whether edits must be published rather than live; whether students may read the curriculum catalogue.

---

## Verdict

**Is V3's timetable functionally equivalent to the institutional reference?**
**No — not in the way a student or the international office currently reaches it.** The *underlying* model is stronger and more correct than the reference: an intake-scoped, offering-linked, enrollment-intersected, role-scoped, audit-backed timetable. But the *product surface* that is supposed to present it — the Academics page — opens on a source catalogue that is not connected to the database, and therefore shows programme narrative with no schedule at all.

**Precisely what is missing or incorrect**

1. **Incorrect:** the Academics intake selector is catalog-driven, and no catalog intake is mapped to a period, so the page can never display the period data that exists (R1).
2. **Missing:** any supported UI/API path that maps the accepted source timetable onto periods and offerings — two incompatible `source_key` conventions and an unexposed importer (R2).
3. **Incomplete:** 3 of 5 sections have no sessions and no teacher; a student sees one of three enrolled courses; the platform's own warnings are not shown in the timetable card (R3).
4. **Missing:** the reference's core artefact — a single programme's week, with a bell-period axis, session-range labels, room badges and a next-session marker — has no dedicated page; it exists only as a filter on a period-wide grid (R4, R8).
5. **Hard to discover:** the timetable is the sixth stacked card, absent from navigation, with no link from the student programme summary (R4).
6. **Missing:** publish/approval semantics, timetable export/print/ICS, timetable search (R7, R8).
7. **Inconsistent:** students can open `/app/academics` although navigation hides it; late enrolment has no recorded authorization/reason (R6, R10).

**Why does the current V3 timetable show program details without the expected schedule?**
Because those two things come from **different sources**. The program details come from the accepted source catalogue (`docs/scu-timetable-domain-map.json`), which is always readable and needs no database. The schedule comes from `class_sections` + `timetable_entries` scoped to `program_offerings.academic_period_id`, and that path is only reachable when a source intake is materialised with the exact `ref:v1:period:*` / `ref:v1:offering:*` keys. In the current baseline no intake has those keys, so `selectedPeriodId` is `null`, the page short-circuits classes and timetable to empty arrays, and the readiness panel honestly reports `Academic period: Not configured`. The schedule is not failing to render — it is never requested, because the selector never points at a period. On the screens that do point at a period (student home, student Timetable tab, staff API), the timetable renders correctly for the data that exists.

**Smallest safe implementation plan**

1. **T1** — make the Academics selector resolve real periods (active period with offerings first) and separate catalog counts from database counts. Small, frontend-only, immediately makes the screen truthful.
2. **T2** — unify the `source_key` contract and expose the existing importer (`prepare`/`apply`/`rollback`) behind `academic.manage_periods` + `academic.manage_timetable`, with dry run, confirmation, batch id and audit. This is the only way real institutional data becomes reachable; it reuses the service that already exists and already respects the section/room/teacher conflict rules.
3. **T3** — surface the reconciliation warnings (sections without sessions/teachers) in the timetable card and on section cards, and list unscheduled enrolled courses under the student grid.
4. **T4** — add the programme/offering week page reusing `WeeklyTimetable`, with the period's bell pattern and `slot_label` when available.
5. **T5** — add the navigation entry and tab the Academics page so the timetable is not the sixth scroll.

No part of this plan introduces a new timetable model, moves ownership to a program, weakens a permission, touches V1, or requires a destructive migration. Items R7 and R10 need institutional decisions before implementation.
