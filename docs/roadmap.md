# 3-Week Implementation Roadmap

## Stage 0 — Freeze scope ✅

## Stage 1 — Foundation ✅ COMPLETE

## Stage 2 — Identity and Authorization ✅ COMPLETE

## Stage 3 — Student Core ✅ COMPLETE

Build:
- [x] Student model with status enum (ACTIVE, INACTIVE, GRADUATED, WITHDRAWN, SUSPENDED)
- [x] Student CRUD API (list, create, retrieve, update, archive)
- [x] Pagination, search, and status filtering
- [x] Student self-service updates (limited fields)
- [x] Authorization enforcement (ADMIN/MANAGEMENT/TEACHER/STUDENT)
- [x] Student directory UI with search and filters
- [x] Student profile UI with tabs for future modules
- [x] Comprehensive test suite (24 new tests)
- [x] All Stage 1+2 tests still pass (68 total)
- [x] Ruff lint passes
- [x] TypeScript type check passes
- [x] Next.js production build passes
- [x] Pytest passes

### Stage 3 Architecture

**Student Model:**
```
Student
├── id (UUID)
├── user_id (FK → users, unique)
├── student_id (unique index)
├── first_name, last_name, preferred_name
├── date_of_birth, gender, nationality
├── phone, emergency_contact_name, emergency_contact_phone
├── status (ACTIVE/INACTIVE/GRADUATED/WITHDRAWN/SUSPENDED)
├── created_at, updated_at
└── user relationship
```

**API Endpoints:**
- GET /api/v1/students/ — List students (paginated, searchable)
- POST /api/v1/students/ — Create student
- GET /api/v1/students/{id} — Get student profile
- PATCH /api/v1/students/{id} — Update student (admin/management)
- PATCH /api/v1/students/{id}/self — Self-update (students only)
- POST /api/v1/students/{id}/archive — Archive student
- PATCH /api/v1/students/{id}/status — Update status

**Authorization Matrix:**
| Operation | ADMIN | MANAGEMENT | TEACHER | STUDENT |
|-----------|-------|------------|---------|---------|
| List students | ✅ | ✅ | ❌ | ❌ |
| Create student | ✅ | ✅ | ❌ | ❌ |
| View any student | ✅ | ✅ | ❌ | ❌ |
| View own student | ✅ | ✅ | ❌ | ✅ |
| Edit student | ✅ | ✅ | ❌ | ❌ |
| Self-update | ❌ | ❌ | ❌ | ✅ |
| Archive student | ✅ | ✅ | ❌ | ❌ |

**Frontend Routes:**
- /app — Dashboard with student directory link
- /app/students — Student directory with search/filter
- /app/students/[id] — Student profile with tabs

**Database Migration:**
- cfe639bbeb30 — Extended student model with status and additional fields

Exit condition:
Management can create and find a complete student record.
**STATUS: ✅ ACHIEVED**

## Stage 4 — Housing

Build data model first:
- buildings
- floors
- rooms
- beds
- assignments

Then:
- visual floor/building interface
- occupancy states
- room drawer
- student cross-links
- assignment/transfer

Exit condition:
Room -> student and student -> room are always consistent.

## Stage 5 — Immigration

Build:
- visa
- residence permit
- expiry calculation
- dashboard
- change requests
- approval workflow
- notifications
- audit history

Exit condition:
Management can see immigration status for all students and students cannot directly overwrite official records.

## Stage 6 — Academic

Build:
- majors
- programs
- courses
- classes
- enrollments
- teachers
- classrooms
- periods
- timetable

Exit condition:
Management edits timetable once and the correct student/teacher views update automatically.

## Stage 7 — Platform

Build:
- announcements
- support tickets
- notifications
- document handling
- basic reports

## Stage 8 — Hardening

Build/test:
- audit logs
- authorization tests
- Playwright critical flows
- error states
- loading states
- accessibility
- backup verification
- monitoring
- production deployment

## MVP exit criteria

The portal is not "production ready" until:
- critical workflows work end-to-end
- authorization is tested
- backups exist and are verified
- production secrets are isolated
- monitoring works
- migrations are controlled
- errors are handled
- staging has been tested
- smoke tests pass
