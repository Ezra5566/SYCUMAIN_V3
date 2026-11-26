# Timetable investigation — reproducible API and database evidence

Captured 2026-11-25/26 against the running dev stack (`school-portal-v2-api` on `:8001`, database `school_portal_v2` on `:5435`). Read-only: every command below is a `GET` or a `SELECT`. Nothing was written.

Login (cookie jar per role; the seeded development password):

```bash
for e in student teacher management admin; do
  curl -s -c cj_$e -o /dev/null -X POST http://127.0.0.1:8001/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$e@school.portal\",\"password\":\"<DEMO_PASSWORD>\"}"
done
```

## 1. Source-intake catalog is entirely unconfigured

```bash
curl -s -b cj_admin http://127.0.0.1:8001/api/v1/academics/source-intakes
```

```text
2026-autumn | period: null | configured: false | imported: false | offerings: 6 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
2026-spring | period: null | configured: false | imported: false | offerings: 5 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
2025-autumn | period: null | configured: false | imported: false | offerings: 4 | active: false | PENDING ['PERIOD_NOT_CONFIGURED']
```

## 2. Database state

```bash
docker exec school-portal-v2-db psql -U portal -d school_portal_v2 -c "
select code,name,source_key,status from academic_periods;
select source_id,source_key,academic_period_id from program_offerings order by source_id;
select cs.section_code, c.code,
 (select count(*) from timetable_entries t where t.class_section_id=cs.id and not t.is_deleted) sessions
 from class_sections cs join courses c on c.id=cs.course_id order by c.code, cs.section_code;"
```

```text
2026-FALL | Fall 2026   | source_key NULL | ACTIVE
2026S     | 2026 spring | source_key NULL | ACTIVE

BAL | seed:2026-FALL:BAL
BBA | seed:2026-FALL:BBA
BCS | seed:2026-FALL:BCS

BA101  A  2 sessions
CS101  A  3 sessions
CS101  B  0 sessions
CS201  A  0 sessions
EN101  A  0 sessions
```

Counts: 28 students, 27 admissions (25 ACTIVE / 1 COMPLETED / 1 WITHDRAWN), 25 open placements, 51 enrollments, 5 sections, 5 live timetable entries, 5 section-offering links.

## 3. Period-scoped reads are correct

```bash
P=$(docker exec school-portal-v2-db psql -U portal -d school_portal_v2 -tAc \
  "select id from academic_periods where code='2026-FALL'")

curl -s -b cj_admin "http://127.0.0.1:8001/api/v1/academics/program-offerings?period_id=$P"
curl -s -b cj_admin "http://127.0.0.1:8001/api/v1/academics/classes?period_id=$P&page_size=100"
curl -s -b cj_admin "http://127.0.0.1:8001/api/v1/academics/timetable?period_id=$P"
```

```text
offerings: BAL, BBA, BCS  (all selectable=true)
classes:   total 5 — CS101-A (BCS, teacher), CS201-A (BCS, no teacher),
           BA101-A (BBA, teacher), EN101-A (BAL, no teacher), CS101-B (BCS, no teacher)
timetable: 5 entries — Counter({'CS101': 3, 'BA101': 2})
```

## 4. The platform's own integrity report

```bash
curl -s -b cj_admin "http://127.0.0.1:8001/api/v1/academics/timetable/reconciliation?period_id=$P"
```

```text
status REVIEW
totals: periods 1, sections 5, live_entries 5, retired_entries 0,
        findings 6, blocking 0, warnings 6
findings:
  SECTION_WITHOUT_TEACHER   count 3  (CS101-B, CS201-A, EN101-A)
  SECTION_WITHOUT_TIMETABLE count 3  (CS101-B, CS201-A, EN101-A)
destructive_actions: false
```

## 5. Student resolution

```bash
SID=$(docker exec school-portal-v2-db psql -U portal -d school_portal_v2 -tAc \
  "select id from students where student_id='STU-001'")
curl -s -b cj_student "http://127.0.0.1:8001/api/v1/academics/students/$SID"
```

```text
program: Bachelor of Computer Science
offering: Bachelor of Computer Science
current_period: 2026-FALL   selected: 2026-FALL   is_current: true
classes: CS201-A, CS101-B, CS101-A
timetable: 3 entries
  Mon 09:00–10:00  CS101-A  B18-301  "Teacher User"
  Wed 09:00–10:00  CS101-A  B18-301  "Teacher User"
  Fri 09:00–10:00  CS101-A  B18-301  "Teacher User"
```

Cross-student access:

```bash
OTHER=$(docker exec school-portal-v2-db psql -U portal -d school_portal_v2 -tAc \
  "select id from students where student_id='STU-102'")
curl -s -o /dev/null -w '%{http_code}\n' -b cj_student \
  "http://127.0.0.1:8001/api/v1/academics/students/$OTHER/timetable"
# 403
```

## 6. Role scoping for classes and timetable

```text
TEACHER     GET /academics/classes  -> total 2  (CS101-A, BA101-A)
            GET /academics/timetable-> 5 entries (only those two sections)
MANAGEMENT  GET /academics/timetable-> 5 entries (unrestricted)
STUDENT     GET /academics/timetable-> own 3 entries (offering ∩ enrollments)
```

Permissions observed on `GET /api/v1/auth/me`:

```text
TEACHER    roles [TEACHER]     academic perms: academic.view
STUDENT    roles [STUDENT]     academic perms: academic.view
MANAGEMENT roles [MANAGEMENT]  academic perms: all academic.manage_* + academic.view
ADMIN      roles [ADMIN]       unrestricted
```

`academic.view` is why a student can open `/app/academics` by URL although `lib/navigation.ts` hides the entry with `hiddenForRoles: ["STUDENT"]`.

## 7. Reference payload

```js
// executed in the browser on https://sycu-timetable.vercel.app/
fetch('/api/timetable').then(r => r.json())
```

```text
keys: metadata, timeSlotFormats, semesters, locations
metadata: { source: "2026-2027-1 专业课表", generated: "2026-10-09",
            timezone: "Asia/Shanghai", totalSemesters: 3,
            totalPrograms: 15, updated: "2026-10-23 09:26" }
timeSlotFormats: standard8 (sessions 1–8), block4 (1-2, 3-4, 5-6, 7-8)
semesters[3] -> programs[15] -> schedule[{day, session, course, location}]
totalRows: 76 · locations: 11
```

No teacher, section, capacity, student, enrollment, date range or week range appears in the payload.

`/admin.js` (loaded by the page, 39,325 bytes) documents: a shipped salted SHA-256 administrator digest, an 8-hour `localStorage` session, editor tabs *Semesters / Programs & classes / Rooms*, localStorage staging, and publishing by exporting `data/timetable.js` (optionally with a token from `POST /api/login`). The panel was not entered; see the report, §11.1.
