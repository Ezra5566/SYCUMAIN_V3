# SYCUMAIN V3 — Engineering Assessment and Production Readiness Analysis

**Date:** 2026-11-24
**Scope:** SYCUMAIN V3 (target) assessed against SYCUMAIN V1 (reference)
**Mode:** Read-only investigation. No V1 file, database, environment or Git state was modified. No V3 code, schema, seed or data was changed. No deployment was performed.
**Data:** Synthetic seed/demo records only. No institutional records were read or migrated.

---

## 0. Project boundaries and method

| System | Root | Role |
|---|---|---|
| SYCUMAIN V1 | `/Users/ezra/SYCUMAIN` | Read-only functional reference (HEAD `4e7158e "version 1 SYCUMAIN FULL FEATURE STATE V 1.0"`) |
| SYCUMAIN V3 | `…/local-projects/6e8bcceb-…/SYCUMAIN_V2` | Target under investigation |

Note on naming: the folder is called `SYCUMAIN_V2`; the product generation analysed here is the one referred to in the brief as **V3**. All paths below are relative to the V3 root unless prefixed with `V1:`.

Commands actually executed (all non-destructive): file/route inspection, `pytest`, `playwright test`, `tsc --noEmit`, `next build`, `alembic current/heads/check`, `docker compose logs/exec`, `psql` **SELECT** queries, authenticated `curl` probes with synthetic demo accounts, `node scripts/ui-audit.mjs`, and `node scripts/check-i18n.mjs`.

Deliberately **not** executed: V1's test suite and V1 migrations (would write to V1's database); V3 migrations, seeds, imports, deletes or any write endpoint; production/staging deploy; load testing.

---

## A. Executive summary

**What V3 actually is.** V3 is not an independent re-implementation. It is a **direct descendant of V1**: the same FastAPI application, the same SQLAlchemy domain model, the same permission constants and student-scope policy, the same Alembic lineage, and the same Next.js page set. `diff -rq` against V1 shows only 21 backend files differ, all additive or extended:

- new `app/auth/activation.py`, `app/seed_demo_full.py`, `app/services/{housing_import,intake_plan,migration_report,timetable_reconciliation}.py`;
- new migration `a7c1e9b25d40_account_activation.py`;
- extensions to `academic`, `housing`, `users` routers, four schemas, `settings.py`, `middleware.py`, `main.py`, `identity.py`, `session.py`, `auth/*`;
- `permissions/constants.py`, `permissions/scope.py`, `permissions/checks.py` are **byte-identical** to V1.

On top of that identical core, V3 replaced the **presentation layer**: a new "Solvik" design system (`src/app/solvik.css`, `motion.css`), a top tab-rail shell replacing V1's sidebar (`app-sidebar.tsx` deleted), accent theming, student peek sheet, image lightbox, and a `/activate` flow. The interface is genuinely modern and internally consistent.

**What works (verified).**
- The API is healthy and its automated suite is strong: **1006 passed, 2 skipped, 0 failed** in 17 min 30 s.
- Authentication, session cookies, role scoping and object-level student access behave correctly under direct probing (teacher sees 19 of 26 students and gets `403` for a non-taught student; student gets `403` on another profile and an empty document list).
- Browser smoke tests on `localhost`: **15 of 16 passed**; all staff modules render real data, all role-scoping assertions pass.
- Localisation is genuinely complete: **2562 keys in all five locales**, 145 runtime-composed keys resolve, 213 backend error codes have messages, `dir="rtl"` is applied for Arabic.
- Responsive/appearance audit: 7 routes × 5 viewports, **0 layout failures, 0 console errors**.
- Migration tooling exists and has been rehearsed on synthetic data (4 intakes, 12 students, preview/apply, activation links).

**What does not work (verified).**
- **`next build` fails outright** — exit 1 — because `next.config.ts` passes a second argument that `createNextIntlPlugin` does not accept. There is no producible frontend artifact today.
- **`tsc --noEmit` fails** on the same line (`next.config.ts(29,68)`).
- **The web Docker image does not contain `messages/`**, yet `src/i18n/request.ts` imports `../../messages/en.json` at module scope. This is the *actual* cause of the original "next-intl" Docker failure. Dev works only because `./apps/web` is bind-mounted over the image.
- **`docker-compose.prod.yml` cannot work**: it builds `target: production` from a Dockerfile that has no such stage; it hardcodes `postgresql://portal:portal@…`, which the production settings validator refuses (verified: `Refusing to start … DATABASE_URL must not use the documented portal:portal credentials`); it terminates no TLS; it passes `NEXT_PUBLIC_API_URL` at runtime only (it is inlined at build time); and it never runs migrations.
- **`alembic check` fails**: the models and the migration head disagree (missing `uq_examination_section`, renamed `immigration_reminders` index).
- **The documented browser-test harness is gone**: `playwright.config.ts` documents `./scripts/e2e.sh` and `docker-compose.test.yml`; neither exists in V3 (both exist in V1). Backup/restore scripts and the `Makefile` are also absent.
- **Institutional settings do not exist** at any layer; the `system.manage` permission is defined and granted to ADMIN but no endpoint consumes it. (This is inherited from V1, not introduced by V3.)

**Why it differs from the intended system.** V3's *backend* is ahead of V1 in several places (account activation, housing/immigration/student import interop, intake planning, timetable reconciliation, migration rehearsal). Its *frontend* is a redesign that was never re-verified against the inherited test suite, its *Docker work* was patched by suppressing a symptom rather than fixing the image, and its *environment* has drifted (two databases, a stale imported-timetable narrative in `docs/`, off-by-one hostnames). The result: a system whose components individually pass their own checks but which cannot be built, packaged or deployed as a whole.

**Overall engineering condition.** Backend and domain logic: **good**. Test coverage: **strong at API level, stale at browser level**. UI: **visually coherent, functionally connected**. Build and delivery: **broken**. Security: **solid baseline with specific gaps**. Production readiness: **not ready — blocked by four independent, verified defects (build, image, compose, migrations)**.

---

## B. Architecture map

### B.1 Runtime topology (actual, as observed)

```
                ┌──────────────────────────────────────────────┐
  Browser ────► │ Next.js 15.5.25 (App Router, React 19)        │  :3101 (dev)
  (cookies)     │ apps/web                                     │
                │  [locale]/… 35 pages, client components       │
                │  next-intl middleware (en zh fr ar ru)        │
                │  AuthProvider → api.getMe()                   │
                └───────────────┬──────────────────────────────┘
                                │ fetch, credentials:"include"
                                │ NEXT_PUBLIC_API_URL (browser)
                                │ API_INTERNAL_URL    (server)
                                ▼
                ┌──────────────────────────────────────────────┐
                │ FastAPI 0.115 / uvicorn                      │  :8001
                │ app/main.py → 21 routers under /api/v1       │
                │ 187 documented paths (web/openapi.json)      │
                │ deps: require_permission() + scope.py        │
                │ services/ (business rules, transactions)     │
                │ SQLAlchemy 2 → psycopg3                      │
                └───────────────┬──────────────────────────────┘
                                │ pool_size=5, max_overflow=10
                                ▼
                ┌──────────────────────────────────────────────┐
                │ PostgreSQL 16   school_portal_v2             │  :5435
                │ 63 tables, 30 alembic revisions              │
                │ head a7c1e9b25d40                            │
                └──────────────────────────────────────────────┘

  Side stores: local document storage (STORAGE_LOCAL_ROOT=var/storage) or S3;
  document bytes never served by URL — always proxied through an authorised route.
  Background work: none. Immigration reminders run once at API startup.
```

Observed containers at inspection time:

| Container | Ports | Status |
|---|---|---|
| `school-portal-v2-api` | 8001→8001 | healthy, 11 h |
| `school-portal-v2-db` | 5435→5432 | healthy |
| `school-portal-v2-web` | 3101→3000 | up (dev server) |
| `sycumain-v2-db` | 5434→5432 | healthy — **orphan/leftover database**, divergent data |
| V1 stack (`school-portal-{api,web,db}`) | 8000 / 3100 / 5433 | running alongside |

### B.2 Request path (traced)

1. A page renders `AppShell` → `AuthGuard` → `useAuth()` → `GET /api/v1/auth/me` with the HttpOnly cookie.
2. Page data comes from a typed client in `src/lib/*-api.ts` (e.g. `studentApi.listStudents`) → `apiFetch` → `${API_BASE}/api/v1/…`.
3. FastAPI resolves the session (`app/auth/dependencies.py`), checks the permission codename (`require_permission`), then the service applies object-level scope (`app/permissions/scope.py`).
4. The service writes through SQLAlchemy; audit rows are written by `record_audit` where present; the router returns a Pydantic schema.
5. `useApi` stores the result, drops stale responses by request id, and the component renders. Existing screens refetch after a mutation by calling `refetch()`.

### B.3 Frontend

| Concern | Implementation |
|---|---|
| Framework | Next.js `^15.0.0` (resolved 15.5.25), React 19, TypeScript 5.5 |
| Routing | App Router, locale-prefixed (`localePrefix: "always"`), 35 `page.tsx` |
| Shell | `src/components/layout/app-shell.tsx` — top tab rail + "More" dropdown + floating dock + mobile `Sheet` |
| UI kit | Tailwind 3.4 + CSS variables (`globals.css`, `solvik.css`, `motion.css`); Radix dialog/dropdown/select/tabs/toast; `class-variance-authority` |
| Icons / toasts | `lucide-react`, `sonner` |
| Theming | `theme-provider.tsx` (light/dark/system) + `accent-picker.tsx` |
| State | React context only (`auth-context.tsx`); no Redux/Zustand/react-query/SWR; custom `useApi` with request-id race guard |
| Forms | Controlled `useState` + manual validation; no react-hook-form/zod on the client |
| Tables | `components/ui/data-table.tsx` + `pagination.tsx` (server-side paging) |
| Charts | None — dashboard visualisations are CSS `conic-gradient` and bars |
| i18n | `next-intl` 4.14.5, static message imports |
| Documents | `pdfjs-dist` 5.4.394, private-proxy preview via blob URLs |

### B.4 Backend

| Concern | Implementation |
|---|---|
| Framework | FastAPI, `app/main.py`, all routes under `/api/v1` |
| Routers | 21 (`students, student_import, academic, housing, immigration, documents, examination, absence, dormitory_attendance, calendar, commencement, announcements, support, notifications, reports, audit, users, placements, admission_changes, admission_verification, health`) |
| Services | 33 modules holding business rules; routers stay thin |
| Data access | SQLAlchemy 2 ORM, `SessionLocal`, explicit transactions in services |
| Validation | Pydantic v2 schemas per module |
| AuthN | DB-backed sessions (`user_sessions`), SHA-256 token hash, bcrypt passwords |
| AuthZ | `require_permission(codename)` + `scope.py` for student object scope |
| Background | None (startup hooks only: seeding, reminders) |
| Files | `storage/{local,s3}.py`, malware scan (`clamav`/`dev-clean`/`eicar-test`/`disabled` fails closed) |
| Audit | `app/audit/service.py`, `record_audit` in 11 of 21 routers |
| Errors | Uniform `{"error":{"code","message"}}`, stable codes, localised client-side |
| Config | Pydantic settings with a hard production validator |

### B.5 Database

63 tables. Core clusters: identity (`users, roles, permissions, staff, students, user_sessions`), admissions (`academic_admissions, admission_verifications, admission_changes, academic_placements`), academic (`academic_periods, majors, programs, program_offerings, courses, class_sections, class_section_program_offerings, enrollments, teacher_assignments, classrooms, timetable_entries, attendance_*, assessments, grades, examinations, examination_sections, examination_results`), housing (`buildings, floors, rooms, beds, housing_assignments`), immigration (`immigration_profiles, immigration_documents, immigration_profile_versions, immigration_change_requests, immigration_reminders`), platform (`announcements, support_tickets, notifications, documents, audit_logs`).

Integrity features present: 150 foreign keys, partial unique index `uq_student_original_admission`, one-current-placement partial unique index, `FOR UPDATE` placement locking plus a global timetable lock to make conflict detection race-free.

### B.6 Localisation

`i18n/routing.ts` declares `en, zh, fr, ar, ru`; `rtlLocales = ["ar"]`; `layout.tsx` emits `<html lang dir>`. Messages are imported statically in `i18n/request.ts`. `timeZone: "Asia/Shanghai"`.

### B.7 Infrastructure

- `docker-compose.yml` (dev): api runs `alembic upgrade head` then `uvicorn --reload`; web builds `infra/docker/Dockerfile.web` and runs `next dev`.
- `docker-compose.prod.yml`: **non-functional** (see §K).
- No reverse proxy, no TLS termination, no CI workflow (`.github` absent), no Makefile, no `scripts/` (backup/restore/smoke/e2e all absent), no monitoring or error-reporting integration.

---

## C. V1 versus V3, module by module

Status legend: **E** equivalent · **E+** equivalent or better · **P** partially implemented · **D** different but functionally valid · **M** missing · **X** incorrect · **NV** not sufficiently verified.

| # | Module | V1 | V3 | Status | Evidence |
|---|---|---|---|---|---|
| 1 | Authentication / sessions | DB sessions, HttpOnly cookie, bcrypt | Same + activation, session list/revoke, password change | **E+** | `auth/service.py`, `auth/router.py`, `test_auth.py`, `test_account_activation.py`; live login/logout probes |
| 2 | Accounts & roles | 4 roles, ~70 permissions | Identical constants + `users.manage_students` delegation, activation issuance | **E+** | `permissions/constants.py` byte-identical; `/app/accounts`; `test_accounts.py` |
| 3 | Student directory & profiles | List/search/filter/paginate, profile tabs | Same, plus peek sheet, photo, bulk status | **E+** | `/app/students`, `/app/students/[id]`; smoke test §I |
| 4 | Student onboarding | Create + account | Same; onboard returns temporary password; migrated accounts get activation instead | **E+** | `students/onboard`, `auth/activation.py`; `test_student_import.py` |
| 5 | Admissions & periods | Episodes, verification, changes, corrections, commencement | Same + intake planning/reconciliation | **E+** | `routers/academic.py` §"Intakes"; `test_intake_and_timetable.py` |
| 6 | Programs & majors | Present | Present, unchanged | **E** | `models/academic.py` |
| 7 | Program offerings | Period-scoped offerings + section links | Same | **E** | 3 offerings in live DB; API `program_offerings` |
| 8 | Courses & sections | Present | Present | **E** | 33 courses / 17 sections docs; live API returns CS101 |
| 9 | Student enrollments | Present | Present; placement-scoped reads | **E+** | 49 enrollments in 2026-FALL |
| 10 | Teacher assignments | Present | Present; scope enforced on reads | **E** | 19/26 visible, 403 outside |
| 11 | Timetables | Sections + entries, conflict detection | Same + reconciliation report + offering links | **E+** structurally, **P** data | §G |
| 12 | Academic attendance | Absence-based | Same | **E** | `test_phase3_attendance_*` |
| 13 | Assessments & grades | Present, publish act | Same | **E** | `classes/{id}/grades`, `grades.publish` |
| 14 | Examinations & results | Present, record/publish split | Same | **E** | `test_examination.py` |
| 15 | Housing administration | Buildings→floors→rooms→beds, assign/transfer/end | Same + CSV allocation import | **E+** | `test_housing*.py`, `housing_import.py` |
| 16 | Dormitory attendance | Separate permission, `/me` self-service | Same | **E** | `test_dormitory_attendance.py` |
| 17 | Immigration profiles | Profile + versions | Same | **E** | `test_immigration.py` |
| 18 | Immigration documents & verification | Upload, verify, trust states | Same | **E** | `documents.py`, `admission_verification.py` |
| 19 | Expiry reminders | Tiered, idempotent, startup + manual | Same | **E** | `immigration_reminders.py`, `test_immigration_reminders.py` |
| 20 | Document management | Private storage, preview, malware scan | Same + inline PDF/image preview | **E+** | proxy-only downloads; IDOR probe returned empty |
| 21 | Announcements | Draft/publish/archive | Same | **E** | `/app/announcements` |
| 22 | Support requests | Tickets, assign, respond, resolve | Same | **E** | `test_platform.py` |
| 23 | Notifications | Per-user, unread count, read-all | Same | **E** | `/notifications/unread-count` |
| 24 | Reports & dashboards | Aggregated overview | Same; dashboard rebuilt on the same API | **E+** | live `/reports/overview`; no hardcoded values found |
| 25 | Audit logs | `audit_logs`, viewer | Same, but only 11 of 21 routers write | **P** | `record_audit` absent from `examination, dormitory_attendance, calendar, commencement, absence, admission_verification` |
| 26 | Institutional settings | Permission only, no surface | **Same gap** | **M** (inherited) | `system.manage` unreferenced anywhere in either codebase |
| 27 | Data import / migration | CSV students (+docs) | CSV students, CSV housing, JSON immigration, preview/apply, interop, rehearsal | **E+** | `docs/data-migration.md`, `test_import_interop.py`, `test_migration_rehearsal.py` |
| 28 | Multilingual & RTL | 5 locales | 5 locales, 2562 keys each, RTL verified | **E+** | `check-i18n.mjs`; `/ar` emits `dir="rtl"` |

### Business rules that V3 changed relative to V1 (all deliberate and defensible)

1. **Migrated accounts receive an activation link, not a password** (`feat: activate migrated accounts instead of issuing passwords`). V1's importer issued a temporary password; V3 stores `UNUSABLE_PASSWORD_HASH = "!"` until activation. Strictly safer; `test_account_activation.py` covers it.
2. **The three importers agree on identity** (`fix: make the three importers agree on who a student is`) — keyed on student number, conflict-reporting instead of overwrite.
3. **Housing allocations importable** with preview/confirmation; never evicts or transfers silently.
4. **Timetable is offering-aware**: `get_student_visible_class_section_ids` prefers the student's current `AcademicPlacement.program_offering_id`, then falls back to enrollments — exactly the adjustment V3's own domain audit (`docs/scu-timetable-domain-audit.md` §1) said was needed but "not applied".
5. **`students.major_id/program_id` projections were dropped** in favour of placements (`f8a1b2c3d4e5_drop_student_academic_projections`); the live `students` table has neither column.

No rule was found that V3 *lost* relative to V1. Permission constants, scope policy, placement locking, attendance rules and examination publication rules are identical.

---

## D. UI audit

### D.1 Page inventory (35 routes)

Public/locale: `/` (redirect), `/login`, `/forgot-password`, `/reset-password`, `/activate`, `/forbidden`, `/unauthorized`, `/session-expired`, `/service-unavailable`, `/[...rest]` (catch-all), error boundaries.

Protected app: `/app` (role-aware dashboard), `/app/profile`, `/app/students`, `/app/students/[id]`, `/app/academics`, `/app/academics/calendar`, `/app/admissions/verification`, `/app/admissions/commencement`, `/app/attendance`, `/app/examinations`, `/app/housing`, `/app/housing/[buildingId]`, `…/[floorId]`, `…/[roomId]`, `/app/immigration`, `/app/documents`, `/app/announcements`, `/app/announcements/[id]`, `/app/notifications`, `/app/support`, `/app/support/[id]`, `/app/reports`, `/app/audit`, `/app/accounts`, `/app/settings`.

Component inventory: 26 primitives in `components/ui`, 3 layout (shell, command menu, language switcher, notification bell, theme switcher), 7 academics, 2 admissions, 5 students, 5 documents, 3 housing, 4 immigration, 2 motion, 2 theme, 1 announcements, 1 support, 1 dashboard, 1 auth, 1 brand.

### D.2 Functional consistency — verified

| Behaviour | Result | Evidence |
|---|---|---|
| Admin login → dashboard | works | smoke test 1 |
| Anonymous → login redirect | works | smoke test 2 |
| Invalid credentials → error, no session | works | smoke test 3 |
| **Sign-out** | works via user menu, **not a visible button** | smoke test 4 fails on `getByRole("button", {name:/sign out/i})`; item lives in `DropdownMenu` (`app-shell.tsx:282-291`) |
| Student directory lists real students | works | smoke test 5 (after origin fix) |
| Profile tabs render content | works | smoke test 6 |
| Housing buildings → floors → rooms → beds | works | smoke tests 7-9 |
| Immigration expiry data | works | smoke test 10 |
| Academics: majors/courses/timetable | works | smoke test 11 |
| Student denied directory, no staff nav | works | smoke tests 13-14 |
| Teacher scoped dashboard | works | smoke test 15 |
| Management reaches staff modules | works | smoke test 16 |
| No console errors / no overflow, 7 routes × 5 viewports | clean | `scripts/ui-audit.mjs` → `failures: []`, `consoleErrors: []` |
| Arabic RTL layout | works | `/ar` → `dir="rtl"`; audit includes `/ar/app` at 390 px |

### D.3 Visual/consistency findings

- The design system is coherent: one token set, one spacing rhythm, Radix-based dialogs/sheets with focus trapping, `rtl:` variants used for directional icons and offsets, tabular numerals on metrics.
- Dashed/absent: no charting library, so trend charts are not available (only composition bars/donuts). Acceptable, but "reports" cannot show time series.
- **Affordance regressions vs V1:** primary navigation moved from a persistent sidebar to a horizontally scrolling tab rail plus a "More" dropdown; sign-out moved from a visible button into an avatar menu. Both are defensible design decisions, but they are *unannounced behaviour changes* relative to the documented flows, and one breaks the inherited smoke test.
- Empty/loading/error states exist per page (`empty-state`, `loading-state`, `error-state`, `status-page`), and `app/error.tsx` distinguishes 403 from a crash.
- Accessibility: semantic landmarks (`banner`, `navigation aria-label="Main navigation"`, `complementary`, `main`), `aria-current` on the active tab, labeled icon buttons, `role="img"` + `aria-label` on CSS charts. Not verified with a screen reader; not audited against WCAG.
- Mobile: a real bottom dock and a `Sheet` menu (19 links) fit within 390×844 per the audit.

### D.4 Where the UI differs from the intended design

The brief says V3 was meant to keep V1's *functions* behind a modern interface. That is what happened functionally; what did **not** happen is reconciliation of the interface's *contract with its own tests and documentation*: the smoke spec still describes V1's sidebar and sign-out button, and the V3 navigation has no equivalent visible control. This is a maintenance defect, not a rendering defect.

---

## E. Backend and database audit

**API coverage.** 187 documented paths across 21 routers; every navigation destination has a backing endpoint except institutional settings (§C#26). `web/openapi.json` is generated and `types:generate` regenerates the client types.

**Business logic.** Rules live in `app/services/*` (33 modules, ~16 k LOC): placement supersession with `FOR UPDATE`, timetable conflict detection under a global lock, one-invalid-row-refuses-the-batch imports, immigration "fill blanks only / never auto-verify", attendance commencement gating, examination record-vs-publish separation.

**Data persistence.** Verified through the running API and database:
- 26 students, 49 enrollments (2026-FALL), 3 offerings, 5 timetable sessions, 63 tables, 150 FKs.
- Mutations observed to persist across requests (login, session cookie, list/detail reads).

**Integrity findings.**

| Finding | Severity | Evidence |
|---|---|---|
| Model/migration drift: `uq_examination_section` missing; `ix_immigration_reminders_profile_id` vs `…_immigration_profile_id` | **High** | `alembic check` → "New upgrade operations detected", exit non-zero |
| No unique constraint enforcement for examination sections at DB level today | High | consequence of the above |
| Audit writes absent for examinations, dormitory attendance, calendar, commencement, absences, admission verification | Medium | grep of `record_audit` per router |
| No institutional settings entity/table | Medium | absent in both V1 and V3 |
| Two divergent development databases (5435: 1 period/26 students; 5434: 2 periods/27 students) | Medium (operational) | `psql` counts in both containers |
| `docs/scu-timetable-reconciliation-report.md` states "22 live timetable entries / 6 offerings"; the running DB has 5 sessions / 3 offerings | Medium | doc vs live query |
| 150 FKs but 63 tables — some high-traffic child tables rely on application-level checks only | Low/Inferred | `pg_constraint` count; not exhaustively mapped |

**Architectural weaknesses.** No repository/unit-of-work abstraction (services use the session directly — acceptable at this size); no optimistic concurrency on most entities (placement/timetable are the exceptions); no soft-delete policy beyond timetable entries and documents; startup performs seeding and reminder reconciliation, which makes cold start slower and couples deployment to data mutation.

---

## F. Authentication, roles and permissions

### F.1 Implementation

- Session cookie `session_token`: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when production (or when explicitly set), 7-day expiry, server-side revocation.
- Token stored as SHA-256; passwords bcrypt via passlib; a provisioned-but-unactivated account stores `"!"`, which can never verify.
- Every request re-checks `user.is_active` **and** the linked student's status, so suspension takes effect immediately.
- Rate limiting in PostgreSQL (login per IP 20/15 min; per account 5/15 min; reset 5/3 per hour).
- Uniform `403` `{"code":"FORBIDDEN"}`; permission denial and object denial are distinguishable only by endpoint behaviour (acceptable, but harder to debug).

### F.2 Role-permission matrix (from `permissions/constants.py`, verified live)

| Capability | ADMIN | MANAGEMENT | TEACHER | STUDENT |
|---|---|---|---|---|
| Student directory list | ✅ | ✅ | ✅ (scoped) | ❌ 403 |
| Own student record (`/students/me`) | n/a | n/a | n/a | ✅ |
| Other student's profile | ✅ | ✅ | ✅ only if taught, else 403 | ❌ 403 |
| Create/edit/archive students | ✅ | ✅ | ❌ | ❌ |
| Admissions & placements | ✅ | ✅ (no admin slot, no original-pointer correction) | ❌ | ❌ |
| Academic structure & timetable | ✅ | ✅ | read only | read only |
| Attendance (class) | ✅ | ✅ | ✅ scoped | read own |
| Dormitory attendance | ✅ | ✅ | ❌ | read own (`/me`) |
| Grades | ✅ | edit | view/edit scoped | read published |
| Examinations | ✅ | manage/record/publish | view/record scoped | read published |
| Housing | ✅ | ✅ | ❌ | read own |
| Immigration | ✅ | ✅ | ❌ | read own + submit change |
| Documents | ✅ | ✅ | ❌ | own view/upload |
| Announcements | ✅ | ✅ | view/create | view |
| Support | ✅ | manage | view/create/respond | view/create |
| Reports | ✅ | ✅ | ❌ | ❌ |
| Audit log | ✅ | ✅ | ❌ | ❌ |
| User administration | ✅ all | students only | ❌ | ❌ |
| Institutional settings | permission exists, no endpoint | ❌ | ❌ | ❌ |

Live probes (synthetic accounts):

```
student:     403 /students/   200 /students/me   200 /academics/timetable
             403 /immigration/overview  403 /housing/overview  403 /users/  403 /audit
teacher:     200 /students/ (19 of 26)  403 for a non-taught student (STU-118)
management:  200 /students/ /immigration/overview /housing/overview /users/ /audit /reports/overview
```

### F.3 Security findings (see §J for severity)

No IDOR was found: `GET /documents?student_id=<other>` returns `{"items":[],"total":0}` for a student, `GET /students/{other}` returns 403, `GET /immigration/profiles/{other}` returns 404. Teacher scoping is enforced server-side, not merely hidden in navigation.

---

## G. Academic and timetable assessment

**Structural support for intake-specific structure: present and correct.**

```
academic_periods (intake)
   └── program_offerings (period-specific main programme)
          └── class_section_program_offerings (M:N)
                 └── class_sections (one canonical teaching section)
                        ├── timetable_entries (day, start, end, classroom)
                        ├── enrollments
                        └── teacher_assignments
students ── academic_admissions ── academic_placements(program_offering_id, academic_period_id)
```

- `get_student_visible_class_section_ids` resolves the student's current placement first and returns that offering's sections; only when no placement exists does it fall back to enrollments. This satisfies "a student's timetable follows their actual academic placement".
- Conflict detection `_timetable_conflict_exists` checks classroom and teacher per period, under a module-level lock, raising stable codes (`TIMETABLE_CONFLICT` family) mapped to 409.
- `POST /academics/intakes/plan` creates missing intakes idempotently and refuses to rewrite dates of an intake that already has students.
- `GET /academics/timetable/reconciliation` reports mismatches between timetable rows and the academic structure.

**Data limitation (verified).** The running database contains **one** period (`2026-FALL`), 3 offerings, 5 timetable sessions. The reconciliation report describes 2026 Autumn applied with 6 offerings / 14 sessions and 2025 Autumn + 2026 Spring *held* because they lack official dates. Therefore:

- Multiple intakes are **supported by the model and services**, but **not demonstrated by the current dataset**.
- The "existing timetable has already been imported" premise is only partly true in this environment: the imported 2026 Autumn set is present in the *other* local database (5434, 2 periods) and not in the database the running API uses (5435). The documentation's counts do not match either exactly.

**What must be corrected:** load/verify the real timetable against the environment actually being used, reconcile 2025 Autumn and 2026 Spring once official dates exist, and add a browser test that proves two intakes show different timetables to two students.

---

## H. Localisation

`node scripts/check-i18n.mjs` (passing):

```
Reference: en.json (2562 keys)
✔ ar: 2562 keys, no problems
✔ fr: 2562 keys, no problems
✔ ru: 2562 keys, no problems
✔ zh: 2562 keys, no problems
✔ dynamic keys: 145 runtime-composed keys resolve in all locales
✔ literal keys: every source translation call resolves in the reference catalog
✔ error codes: all 213 backend codes have a message
  note: 52 reserved codes not yet emitted by the API
```

| Locale | Keys | Status | RTL |
|---|---:|---|---|
| en | 2562 | complete | ltr |
| zh | 2562 | complete | ltr |
| fr | 2562 | complete | ltr |
| ru | 2562 | complete (large catalogue, RU is first-class) | ltr |
| ar | 2562 | complete | **rtl verified** (`<html dir="rtl">`) |

Comparison with V1: V3 has 98 additional keys (activation, audit actions, document rotate, view-all) and lost 2 (`students.intake.credentialsHeading/Hint`, replaced by the activation flow). Nine values were reworded.

Residual risks: (a) `next.config.ts` injects a decoy `localeMessages` object (`hello`/`world`) that would be catastrophic if next-intl ever honoured it — today it is ignored, but it is a trap; (b) `messages/messages/*.json` contain `{}` and are untracked junk; (c) translations are validated statically, not in a browser for all five locales (only `/ar` is exercised by the audit).

---

## I. Testing results (exact)

| Suite | Command | Result |
|---|---|---|
| API (pytest) | `SYCUMAIN_TEST_DATABASE_URL=…:5434/school_portal_test_v2 .venv/bin/python -m pytest -q` | **1006 passed, 2 skipped, 0 failed, 23 warnings in 1050.23 s (17:30)**, exit 0 |
| Browser smoke (localhost) | `E2E_BASE_URL=http://localhost:3101 E2E_API_URL=http://localhost:8001 playwright test e2e/smoke.spec.ts` | **15 passed, 1 failed in 1.9 m**, exit 1 |
| Browser smoke (127.0.0.1) | same with `127.0.0.1` | 7 passed, 9 failed — all auth/cookie origin effects, not application logic (see below) |
| TypeScript | `tsc --noEmit` | **1 error**: `next.config.ts(29,68) TS2554 Expected 0-1 arguments, but got 2` |
| Production build | `next build` | **FAILED**, exit 1, same error (compiled successfully, then "Linting and checking validity of types" failed) |
| Migration drift | `alembic check` | **FAILED** — 3 pending operations |
| i18n | `node scripts/check-i18n.mjs` | passed |
| Responsive/appearance | `node scripts/ui-audit.mjs` | 7 routes × 5 viewports, `failures: []`, `consoleErrors: []` |
| V1 suite | not run | intentionally not executed to keep V1 read-only |
| Load / performance | not run | no load generator or environment available; no results are claimed |

**The one smoke failure, explained precisely.** `logout returns to login…` waits for `getByRole("button", { name: /sign out/i })`. V3 renders sign-out as a `DropdownMenu.Item` inside the avatar menu (`components/layout/app-shell.tsx:282-291`), so no such button exists. Logout itself works; the test encodes V1's sidebar layout.

**The nine `127.0.0.1` failures, explained precisely.** Pages served from `127.0.0.1:3101` call the API at `localhost:8001`. Those are different *sites*, so the `SameSite=Lax` session cookie is not sent; `/auth/me` returns 401 and `AuthGuard` redirects to `/login`. Screenshots confirm the login page. Re-running with `localhost` for both origins produced 15/16. This is a development-origin footgun (documented in V1's README, not in V3's), not an authorisation defect.

**Coverage characterisation.** The API suite is unusually strong for this class of project: real PostgreSQL, savepoint-isolated transactions, role/object-scope tests (`test_authorization_scope.py`, `test_privilege_boundaries.py`), production-config tests, security-header tests, import interop, migration rehearsal, and idempotency assertions. It is *not* perfect: there is no test that exercises the Next.js build or the Docker image, which is exactly where the four blocking defects live.

**Missing test infrastructure (verified).** `playwright.config.ts` documents `./scripts/e2e.sh` and `docker-compose.test.yml`; V3 has neither. There is no CI configuration, no Makefile, and no backup/restore scripts (V1 has all of these).

---

## J. Security findings

Baseline is good: HttpOnly session cookies, hashed tokens, bcrypt, rate limiting, uniform error envelopes, security headers (`nosniff`, `DENY`, `no-referrer`, `Permissions-Policy`, `CORP`, HSTS in production), API docs disabled in production, a production configuration validator that refuses weak secrets and `portal:portal`, malware scanning that fails closed, private document proxying, and server-enforced object scope.

| # | Severity | Finding | Confirmed / inferred | Evidence |
|---|---|---|---|---|
| S1 | **Critical** | Production deployment cannot start: `docker-compose.prod.yml` hardcodes `DATABASE_URL` with `portal:portal`, which the settings validator rejects | **Confirmed** | Isolated `Settings()` run with every other production variable correct → `Refusing to start … DATABASE_URL must not use the documented portal:portal credentials` |
| S2 | **Critical** | No producible frontend artifact: `next build` exits 1 | **Confirmed** | `/tmp/v3_build.log` |
| S3 | **High** | Web image omits `messages/`, so any built image fails i18n resolution | **Confirmed** | `docker run --entrypoint sh sycumain-v2-web:latest -c 'ls /app'` → no `messages`; `i18n/request.ts` imports `../../messages/en.json` |
| S4 | **High** | Schema drift: models and migration head disagree; a uniqueness invariant exists only in code | **Confirmed** | `alembic check` |
| S5 | **High** | No TLS termination / reverse proxy in the production compose; web publishes `443:3000` in plaintext | **Confirmed (config)** | `docker-compose.prod.yml` |
| S6 | **Medium** | `NEXT_PUBLIC_API_URL` supplied only at runtime in production; it is inlined at build time, so a prod bundle would call the fallback `http://localhost:8000` (V1's port) | **Confirmed (config)** | `docker-compose.prod.yml` vs `api.ts` |
| S7 | **Medium** | No audit trail for examinations, dormitory attendance, calendar, commencement, absences or admission verification | **Confirmed** | `record_audit` absent from those routers |
| S8 | **Medium** | Dev stack enables `PASSWORD_RESET_DELIVERY=dev`, returning reset tokens in the HTTP response; safe by validator in prod, dangerous if the dev compose is ever exposed | **Confirmed** | `docker-compose.yml`; `reset-availability` → `{"available":true,"delivery":"dev"}` |
| S9 | **Medium** | Dev stack runs `MALWARE_SCANNER=dev-clean` (no inspection); rejected in production, but would silently accept infected files if the dev stack were reused | **Confirmed** | compose env; settings validator |
| S10 | **Low** | No CSRF token; protection relies on `SameSite=Lax` plus JSON-only bodies | **Inferred** | cookie settings; no CSRF middleware |
| S11 | **Low** | `X-Frame-Options: DENY` without a matching `frame-ancestors` CSP on the web app | Inferred | API middleware only applies to API responses |
| S12 | **Low** | Docker work is uncommitted (`next.config.ts`, `request.ts`, `api.ts`, `package.json`, compose, `infra/`) | Confirmed | `git status` |
| S13 | **Informational** | 52 reserved error codes have translations but are never emitted (dead catalogue) | Confirmed | `check-i18n.mjs` note |
| S14 | **Informational** | `messages/messages/*.json` are `{}` stubs left behind by a mistaken path | Confirmed | `wc -c` |
| S15 | **Informational** | Decoy `localeMessages: {hello, world}` in `next.config.ts` — ignored today, catastrophic if honoured | Confirmed | plugin signature; TS error |

No SQL injection, XSS, SSRF or privilege-escalation issue was found. All queries are ORM-parameterised; React escapes output; no user-supplied URL is fetched server-side; role changes are permission-gated and audited (`test_role_transition.py`). This is **not** a security certification — no penetration test, dependency CVE scan, or production TLS review was performed.

---

## K. Deployment and scalability

**Can V3 be deployed reliably today? No.** Four independent blockers (S1–S5), each sufficient on its own:

1. `next build` fails → no artifact.
2. `Dockerfile.web` has no `production` stage → `docker-compose.prod.yml` cannot build.
3. API refuses to start in production because of the hardcoded DB credentials.
4. No migration step in the production command; no reverse proxy/TLS.

**Capacity reasoning for ~1500 registered users (not measured).** Realistic concurrency for this workload is a few dozen staff sessions plus a few hundred students reading timetables/announcements at peak. On paper that is well within one API instance: 187 endpoints, indexed lookups, 5+10 connection pool, pagination everywhere. Risks: a single uvicorn process (no `--workers`), no caching layer, and report endpoints that aggregate across tables. **No load test was run, so no throughput or latency claim is made.**

**Performance observations (static, not benchmarked).** Frontend ships `pdfjs-dist` and `world-map-country-shapes`; `pdfjs` is lazily confined to the preview dialog but adds a large async chunk. Next's build warns about multiple lockfiles (root `package-lock.json` + `apps/web/pnpm-lock.yaml`), so `outputFileTracingRoot` should be pinned for standalone builds. Dashboard rendering is CSS-only (cheap). No N+1 pattern was identified in the student list path, but this was not profiled.

**Operational gaps.** No backups/restore scripts, no monitoring/error reporting, no log aggregation config, no health-based restart policy on web, no scheduled job runner (reminders only run at startup), no documented RTO/RPO, and settings for data retention left deliberately unset.

---

## L. Institutional migration readiness

**What exists (verified in code, docs and tests).**

| Capability | Status |
|---|---|
| CSV student import with dry-run and atomic apply | ✅ `POST /students/import?dry_run=` |
| Duplicate detection within a file and against the directory | ✅ `test_student_import.py`, `test_import_interop.py` |
| Student-number identity matching across all three importers | ✅ commit `adfea31` |
| Housing allocation CSV import (preview → apply) | ✅ `housing_import.py`, `test_housing_import.py` |
| Immigration JSON import keyed by student number, never auto-verified | ✅ `docs/data-migration.md` |
| Relationship validation (building/room/bed must exist) | ✅ |
| Audit record per applied run | ✅ `student.import.applied`, `housing.import.applied`, `immigration.import.applied` |
| Safe retry / idempotency | ✅ tested |
| Account provisioning + first-login activation | ✅ `auth/activation.py`, `test_account_activation.py` |
| Intake planning for 2025-FALL, 2026-SPRING, 2026-FALL, 2027-SPRING | ✅ `POST /academics/intakes/plan` |
| Rehearsal on synthetic data | ✅ `docs/migration-rehearsal-report.md`: 4 intakes, 12 students, 12 housing, 12 immigration, 0 conflicts, 12 activation links, 4 activated |
| XLSX support | ❌ CSV only (no `openpyxl` dependency) |
| Rollback / compensation | ❌ none; the model is "report and refuse", not "undo" |
| Timetable bulk import as an endpoint | ⚠️ reconciliation/report exists; the reference import was a documented one-off applied to a development database |
| Conflict/reconciliation report | ✅ `GET /academics/timetable/reconciliation` |

**Assessment.** The migration *capability* is materially better than V1's and is the strongest part of V3. What is missing for the real dataset is operational, not architectural: an XLSX path (the institution's files are spreadsheets), a documented rollback position, and an environment in which the imported timetable actually matches what is being assessed.

---

## M. Root-cause analysis — why V3 "does not behave as expected"

Ordered by explanatory power.

1. **A build-breaking "fix" is mistaken for a working Docker setup.** The next-intl Docker error was real, but its cause was a missing `COPY messages`. Instead, `next.config.ts` was given a non-existent `localeMessages` option (and a decoy message object). The dev container works because of the bind mount; `next build` and `tsc` now fail. *Category: configuration/build defect.*
2. **The interface was redesigned without re-baselining its contract.** Navigation, sign-out and several labels changed; the inherited smoke spec, the docs and the reviewer's expectations still describe V1. 15 of 16 behaviours work, yet the suite reports failure. *Category: UI/test-contract defect.*
3. **The environment drifted.** Two databases with different datasets, a documented timetable import that is not in the database the API uses, and ports 5433/5434/5435 in play. Any observation of "the timetable is wrong" is unreliable until one environment is declared canonical. *Category: environment/data defect.*
4. **Production packaging was never exercised.** The prod compose references a stage that does not exist, credentials the validator rejects, no TLS and no migrations. Nothing in CI or the test suite builds either artifact. *Category: infrastructure defect.*
5. **Schema drift.** `alembic check` fails; a uniqueness invariant is application-only. *Category: database defect.*
6. **Inherited functional gaps are perceived as V3 regressions.** No institutional settings, partial audit coverage, no email delivery for password reset. These are V1 gaps carried forward. *Category: business-rule gap (inherited).*
7. **Dev-origin footgun.** Page on `127.0.0.1`, API on `localhost` ⇒ no cookie ⇒ apparent total auth failure. *Category: configuration defect.*

---

## N. Remediation roadmap

Sequenced; each item names its dependency and how it will be verified. Nothing here was executed.

### 1. Critical architectural and security corrections
1. **Restore a valid Next config.** Remove the second plugin argument and the decoy object; keep `output: "standalone"`; pin `outputFileTracingRoot`.
   *Verify:* `tsc --noEmit` exit 0; `next build` exit 0; `next start` serves `/en`.
2. **Fix the web image.** `COPY apps/web/messages ./messages` in every stage; add a real `production` stage (`builder` → `runner` on `.next/standalone`); pass `NEXT_PUBLIC_API_URL` as a **build arg**.
   *Verify:* `docker build --target production`; `docker run` image without mounts; page renders translated text.
3. **Repair the production compose.** `DATABASE_URL` from `${POSTGRES_PASSWORD}`; add a reverse proxy with TLS (V1's `infra/caddy` is a usable reference); run `alembic upgrade head` as a one-shot job; keep `SESSION_COOKIE_SECURE=true`.
   *Verify:* `ENVIRONMENT=production` settings load; `docker compose -f docker-compose.prod.yml config`; stack reaches healthy; HTTPS login works.
   *Depends on:* 1, 2.
4. **Commit the Docker work.** The entire deployment path is currently untracked.
   *Verify:* clean `git status`; a fresh clone builds.

### 2. Backend and database stabilisation
5. **Close the schema drift** with a new revision adding `uq_examination_section` and renaming the reminders index; then `alembic check` must pass.
6. **Declare one canonical development database**; retire the 5434 container or rename it explicitly as a rehearsal database. Re-seed deterministically.
   *Verify:* counts in `docs/` match the live DB; `test_migration_rehearsal.py` passes against the declared DB.

### 3. Authentication and permission corrections
7. Re-verify the matrix with the existing `test_privilege_boundaries.py`; add explicit tests for the two surfaces with no coverage today (documents-of-another-student by teacher, immigration change requests by management).
8. Add a visible, keyboard-reachable sign-out control (or update the smoke contract and document the menu). Prefer the control: it is a security affordance.

### 4. Academic and timetable corrections
9. Apply/verify the real timetable in the canonical environment for 2026-FALL; reconcile 2025-AUTUMN and 2026-SPRING once official dates exist.
10. Add a two-intake browser test: two students, different offerings, different timetables, no cross-leak; plus a conflict-rejection test (admin double-books a room → 409).
    *Depends on:* 6, 9.

### 5. UI/backend integration completion
11. Re-baseline `e2e/` against the V3 shell (sign-out, top-rail navigation, labels) and restore the documented harness: `docker-compose.test.yml` + `scripts/e2e.sh`.
12. Verify every mutation path in the browser at least once (onboard, assign bed, transfer, record absence, publish grade, upload document, resolve ticket).

### 6. Multilingual completion
13. Remove `messages/messages/*.json`; add a browser i18n check for zh/fr/ru/ar (not only `/ar`); assert RTL table and dialog behaviour, not just `dir`.

### 7. Migration capability
14. Add XLSX ingestion (or a documented conversion step), a rollback/compensation position, and a signed reconciliation report per intake.
    *Depends on:* 6, 9.

### 8. Performance and deployment readiness
15. Run a realistic load test (≈50 concurrent staff, ≈300 concurrent students) against the production-shaped stack; record p95 latency and error rate. Add `--workers` or a process manager only if measurements justify it.
16. Add backups (nightly `pg_dump` + document-store copy), a restore rehearsal, uptime/error monitoring, and a scheduled job for reminders instead of startup-only.

### 9. Final certification
17. Staging UAT per role; security review of the deployed origin (TLS, headers, cookie attributes); migration dry-run on a copy of the institutional data; only then production.

---

## O. Final readiness verdict

Deliberately **not** combined into a single percentage.

| Dimension | Verdict | Basis |
|---|---|---|
| **Development stability** | **Amber** | API suite green (1006/1008); dev stack runs; but `tsc` and `next build` fail and the deployment path is uncommitted |
| **Functional completeness** | **Green–Amber** | All 28 modules present; 27 equivalent-or-better vs V1; institutional settings missing (inherited); timetable data only one intake |
| **Security** | **Amber** | Sound baseline, no IDOR/injection found; one confirmed production-start blocker, partial audit coverage, no pen-test |
| **Data integrity** | **Amber** | Strong domain constraints and locking; `alembic check` fails; two divergent databases |
| **UI functionality** | **Green** | 15/16 browser flows pass; 0 layout/console failures across 35 routes × 5 viewports; one affordance regression |
| **Localization** | **Green** | 2562/2562 keys in 5 locales; RTL verified; static-only validation for 4 locales |
| **Institutional UAT** | **Red** | No UAT environment with canonical data; timetable premise unverified; cannot invite the institution yet |
| **Staging deployment** | **Red** | Cannot build a frontend artifact or start the production API |
| **Real-data migration** | **Amber** | Tooling and rehearsal exist and are good; no XLSX, no rollback, environment not canonical |
| **Production deployment** | **Red** | Four independent blockers (build, image, compose, migrations); no TLS, no backups, no monitoring |

**Bottom line.** V3's domain layer, API and test suite are in better shape than the brief assumes, and its interface is modern and genuinely functional. The system fails as a *product* because the delivery path is broken and the environment is ambiguous — not because the business logic is missing. The shortest credible route to a deployable system is the four build/packaging fixes (§N.1), followed by environment consolidation and re-baselining the browser suite. No architectural rewrite is justified by anything found here.

---

### Evidence index

- Test logs: `/tmp/pytest_v3.log` (1006 passed), `/tmp/pw_v3_localhost.log` (15/16), `/tmp/pw_v3.log` (origin-mismatch run), `/tmp/v3_build.log`, `/tmp/ui_audit_v3.log`.
- Commands: `alembic current|heads|check`, `psql` SELECTs on `school_portal_v2`, authenticated `curl` probes (`/students/`, `/students/me`, `/documents?student_id=`, `/immigration/profiles/{id}`, `/reports/overview`, `/auth/password/reset-availability`), `docker run --entrypoint sh sycumain-v2-web`, `node scripts/check-i18n.mjs`, `node scripts/ui-audit.mjs`.
- Key files: `apps/web/next.config.ts`, `apps/web/src/i18n/request.ts`, `apps/web/src/lib/api.ts`, `apps/web/src/components/layout/app-shell.tsx`, `infra/docker/Dockerfile.web`, `docker-compose.prod.yml`, `apps/api/app/config/settings.py`, `apps/api/app/permissions/{constants,scope,checks}.py`, `apps/api/app/services/academic.py`, `apps/api/alembic/versions/`, `docs/{data-migration.md,migration-rehearsal-report.md,scu-timetable-*.md}`.
