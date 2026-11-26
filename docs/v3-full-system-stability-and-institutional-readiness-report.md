# SYCUMAIN V3 — Full System Stability & Institutional Readiness Report

**Assessment date:** 2026-11-25
**Subject:** `SYCUMAIN_V2` (SYCUMAIN V3), branch `main`, HEAD `8467300`
**Working tree:** 54 modified, 50 untracked, 0 deleted, 0 stashes — nothing committed, staged or pushed
**Reference installation:** `/Users/ezra/SYCUMAIN` (V1) — read-only throughout, never touched

**Evidence tags used throughout**

| Tag | Meaning |
|---|---|
| **VERIFIED** | Reproduced during this assessment, or re-checked against the exact current code |
| **CARRIED** | A prior report's result that still applies to this tree, with the reason it still applies |
| **NOT VERIFIED** | Not tested; no claim made |
| **ESTIMATED** | Derived from measurements with stated assumptions |
| **INSTITUTIONAL DECISION REQUIRED** | Cannot be resolved by engineering alone |

---

## A. Executive verdict

Seven separate decisions, not one green light.

| Decision | Verdict | Basis |
|---|---|---|
| **Functionally stable** | **GO** | 1,059 backend tests pass, 10/10 browser authentication scenarios, 60-minute soak with 0 session failures, 64/64 tables restore byte-identically |
| **Internal demonstration** | **GO** | Fresh initialisation produces working accounts; 144/144 pages build; all five locales render |
| **Controlled institutional UAT** | **CONDITIONAL GO** | Sign-in, roles, permissions and sessions are certified. Conditions: named accounts instead of the shared demo password, a production build, and a written decision on which admission gates are open |
| **Limited institutional operation** | **NO-GO today** | No university-server deployment has run; retention policy unset; no malware-scanner endpoint; document upload is therefore non-functional in a production composition |
| **Full production deployment** | **NO-GO** | The four Phase 9 items below are all still open |
| **Real-data migration** | **NO-GO** | No rehearsal on a copy of institutional data; no rollback exercise |
| **Commit as stable baseline** | **GO** | No secrets, no destructive upgrade path, no binary changes, no unexplained files; grouping in §L |

**The one-sentence answer:** the application is a stable, internally consistent, well-audited development baseline that can be demonstrated and put in front of university staff for UAT — but it cannot carry real student records onto a university server until four deployment items and four institutional decisions are closed, and none of those are code defects.

---

## B. System architecture

### B.1 What actually runs

```
                    ┌───────────────────────────────────────────────┐
  browser  ────────▶│  Next.js 15 (App Router, RSC)                 │
  :3101 (dev)       │  apps/web                                     │
                    │  · [locale] segment: en / zh / fr / ru / ar   │
                    │  · middleware: locale + auth routing (46.3 kB)│
                    │  · 173 references to /api/v1 in src/lib       │
                    └───────────────────┬───────────────────────────┘
                                        │  HTTP + session cookie
                                        │  (SSR uses API_INTERNAL_URL)
                    ┌───────────────────▼───────────────────────────┐
                    │  FastAPI (Python 3.11), uvicorn               │
                    │  apps/api, prefix /api/v1, 22 routers         │
                    │  · ASGI origin/CSRF middleware                │
                    │  · permission checks per endpoint (77 perms)  │
                    │  · services/ layer holds business rules       │
                    │  · SQLAlchemy 2.x + Alembic                   │
                    └───────┬───────────────────────┬───────────────┘
                            │                       │
              ┌─────────────▼──────────┐   ┌────────▼─────────────────┐
              │ PostgreSQL 16          │   │ document store            │
              │ :5435 dev              │   │ STORAGE_BACKEND=local     │
              │ db school_portal_v2    │   │ apps/api/var/storage (dev)│
              │ 64 tables, 150 FKs     │   │ named volume (production) │
              └────────────────────────┘   └──────────────────────────┘
                            │
              ┌─────────────▼──────────────────────────────────────┐
              │ optional: SMTP relay (off by default), ClamAV      │
              │ (real daemon verified in the production rehearsal) │
              └────────────────────────────────────────────────────┘
```

**Port map (verified listening during this assessment):** V3 web 3101 · V3 API 8001 · V3 DB 5435 · V1 web 3100 · V1 API 8000 · V1 DB 5433 · pytest fixture DB 5434.

### B.2 Components, verified against source and runtime

| Layer | Implementation | Evidence |
|---|---|---|
| Frontend | Next.js App Router, RSC, next-intl, Tailwind; standalone output | **VERIFIED** — `next build` 144/144 static pages; 5 locale bundles |
| Backend | FastAPI + SQLAlchemy 2 + Pydantic v2; routers → services → models | **VERIFIED** — 22 `include_router` calls, `services/` layer present |
| Database | PostgreSQL 16, Alembic head `c4d7e91b2f68` | **VERIFIED** — container reports head; `alembic check` clean |
| Auth | Server-side `user_sessions` rows; opaque session cookie (`HttpOnly; SameSite=Lax; Secure` in production); bcrypt hashing; admin-assisted recovery | **VERIFIED** — 81 live session rows; 10/10 browser scenarios; cross-origin PATCH → 403 |
| Authorization | Permission strings per endpoint (77 for ADMIN), object-scope checks in services | **VERIFIED** — `401` unauthenticated, `403` cross-origin, role-gated browser check |
| Background work | In-process: startup seeding, reminder reconciliation, email outbox drain | **VERIFIED in code**; no external scheduler (roadmap P2-4) |
| Documents | Local filesystem backend; checksum recorded per document | **VERIFIED** — 14/14 rows match stored bytes |
| Integrations | SMTP (optional, disabled), ClamAV (real daemon verified once) | **CARRIED** — `test_email_delivery.py`, prod rehearsal §7 |
| Deployment | `docker-compose.yml` (dev), `.test`, `.perf`, `.prod` + Caddy | **VERIFIED** — all four validate; prod rehearsal ran once |
| Observability | Structured logs, `SLOW_REQUEST_MS=1500`, `/health`, `/ready` | **VERIFIED present**; no metrics endpoint, no alerting (**CARRIED**) |
| Backup | `scripts/backup.sh` / `restore.sh` + SHA-256 manifest | **VERIFIED end to end** — see §I.4 |

### B.3 Coupling and configuration honesty

- **No hidden frontend→database path.** No `pg`, `psycopg`, `mysql2`, `better-sqlite3` or Prisma import exists anywhere in `apps/web` (**VERIFIED** by import-statement search). All data access goes through `/api/v1`.
- **Business rules are server-side.** Retired direct-placement writes refuse the whole request (`PLACEMENT_DIRECT_WRITE_RETIRED`) rather than being filtered in the UI — a caller bypassing the UI still gets the rule.
- **One deliberate dev/production divergence:** the login page renders demo account chips only when `NODE_ENV !== "production"`, and production artifacts were inspected with 0 credential occurrences (**CARRIED**, Phase 8 §2.2).
- **A real configuration trap remains:** run from the host virtualenv, `alembic` targets `localhost:5433` (V1's database) and reports `a7c1e9b25d40`, while the api container reports `c4d7e91b2f68 (head)`. This is the single most dangerous operational footgun in the tree (**VERIFIED**). Migrations must only be run through `docker compose exec api python -m alembic …`.
- **No institutional settings module.** There is no settings router: operational policy lives in environment variables, not in the database. That is a legitimate design choice, not a missing feature, but it means every policy change is a redeploy.

---

## C. Module-by-module functionality matrix

Status is "certified" only where the current tree has suite coverage **and** either browser evidence or a live API reproduction. Functional depth beyond that is carried from `docs/functional-certification-v3.md`, which certified the same code.

| # | Module | Status | Verified | Remains unverified | Institutional use |
|---|---|---|---|---|---|
| 1 | Authentication & accounts | **CERTIFIED** | 4 roles sign in; forced password change; admin reset; revocation; 60-min soak | Firefox; real SMTP reset mail | Yes |
| 2 | Students | **CERTIFIED** | Create/read/update/status change; live PATCH round-trip today | Bulk import at 500+ rows on real files | Yes |
| 3 | Student import / export | **CERTIFIED** | Suite; row/size limits enforced | Real CSV variants from the registrar | Yes |
| 4 | Admissions & lifecycle | **CERTIFIED** | Suite; status history table populated (27 rows) | — | Yes |
| 5 | Admission changes & placements | **CERTIFIED** | Suite; 10/10 concurrent re-writes correctly refused `409` | — | Yes |
| 6 | Admission verification | **CERTIFIED** | Suite; original-admission history written | — | Yes |
| 7 | Academic structure | **CERTIFIED** | Suite; period date-correction workflow | — | Yes |
| 8 | Enrollment | **CERTIFIED** | Suite; capacity refusal `400` under 20 concurrent attempts | — | Yes |
| 9 | Timetable | **CERTIFIED** | Suite; student timetable rendered live | — | Yes |
| 10 | Class attendance | **CERTIFIED** | Suite; 12 concurrent writes → 1 row, 0 duplicates | — | Yes |
| 11 | Absence & commencement | **CERTIFIED** | Corrections supersede rather than overwrite; previous date recorded | — | Yes |
| 12 | Dormitory attendance | **CERTIFIED** | Suite | — | Yes |
| 13 | Examinations & grades | **CERTIFIED, caveat** | Suite; `previous_score` retained on the examination correction path | Class-grade path logs identifiers only (§D.3) | Yes, with caveat |
| 14 | Housing | **CERTIFIED** | Suite; 12 concurrent bed claims → 1 success, 11 × `409 BED_OCCUPIED` | — | Yes |
| 15 | Immigration | **CERTIFIED** | Suite; 10 concurrent updates → 10 history rows covering every accepted write | — | Yes |
| 16 | Documents & storage | **CERTIFIED (dev)** / **LIMITATION (prod)** | 14/14 checksums match; real ClamAV `201 CLEAN`; scanner down → `503` fail-closed | Production scanner endpoint | Dev only |
| 17 | Announcements | **CERTIFIED** | Suite; create/update/publish/archive audited | — | Yes |
| 18 | Notifications | **CERTIFIED (in-app)** | Suite; polling stable through the soak | Email delivery (disabled by design) | Yes, in-app |
| 19 | Support requests | **CERTIFIED** | Suite; create/update audited | — | Yes |
| 20 | Reports | **CERTIFIED** | Suite; overview `200` under load | Retention-dependent reports answer "policy pending" | Yes |
| 21 | Audit log | **CERTIFIED (read)** | Live: correct actor, entity, timestamp, IP; `401` without a session | Append-only enforcement (§D.4) | Yes, with caveat |
| 22 | Users, roles, permissions | **CERTIFIED** | 77 permissions for ADMIN; role change audited | — | Yes |

**Not present, and not a defect:** third-party SSO/OAuth, a settings administration module, an external job scheduler, monitoring/metrics export. None of these is required for the stated workflows.

---

## D. Historical record and audit assessment

### D.1 Design

`record_audit()` stages an entry **on the caller's transaction and never commits on its own**. A failed change therefore cannot leave a success record, and a rolled-back change cannot leave an orphan audit row. Sensitive keys (`password`, `token`, `passport_number`, `content`, `checksum`, …) are redacted recursively at write time. `audit_logs` stores references and safe metadata only (**VERIFIED** in `app/audit/service.py`).

Coverage is broad: **54 `record_audit()` call sites across routers** (159 usages across the application), with stable machine-readable action codes.

### D.2 Live verification (performed today)

A real change was driven through the API and then checked at both the API and database layers:

```
login admin@school.portal                      → 200 (77 permissions)
PATCH /api/v1/students/{STU-001} preferred_name = "AuditProbe"
                                              → 200, readback "AuditProbe"
GET /api/v1/audit?action=student.updated      → 200, total = 1
row: action=student.updated  actor_email=admin@school.portal
     entity_type=student     entity_id=9d4cf33a-…
     created_at=2026-11-25T18:08:36.602747+00  ip=192.168.65.1
     context={"fields":["preferred_name"]}
PATCH preferred_name back to its original empty value
                                              → 200, value restored, 2 rows total (no duplicates)
GET /api/v1/audit without a cookie            → 401
PATCH from Origin: https://evil.example       → 403
```

**VERIFIED:** the affected record, the action, the authenticated actor and role, an accurate timestamp, the originating request context and the request IP are all captured; the sequence survives the change; repeated operations do not duplicate rows.

### D.3 What history actually preserves, per event

| Event | Who/what/when | Previous → new state | Reason/justification |
|---|---|---|---|
| Student creation | Yes (`student.created`, `account.created`) | n/a (creation) | n/a |
| Student profile edit | Yes (`student.updated`) | **Field names only — values not recorded** | n/a |
| Student status change | Yes | **Yes** (`from`/`to`, bulk flag) | n/a |
| Account role change | Yes (`account.roles_changed`) | **Yes** (`from`/`to`) | n/a |
| Account activation / deactivation / password reset / session revocation | Yes | State recorded | Reset reason not required |
| Attendance submission | Yes | Unique per student/date; duplicates refused | n/a |
| Absence recorded / corrected / cancelled | Yes | **Yes** — correction *supersedes* and stores `previous_absence_date`; cancellation retires without deleting | **Yes** — reason stored |
| Assessment grade (class path) | Yes (`academic.grade.updated`) | **Identifiers only — prior score not in the audit context** | n/a |
| Assessment grade (examination correction path) | Yes | **Yes** — `previous_score` retained | Correction path |
| Housing assign / transfer / move-out | Yes | **Yes** — `from_assignment_id` + new bed; the old assignment row is retained | Notes stored |
| Immigration document update | Yes | **Yes** — the concurrency run produced 10 history rows for 10 accepted writes | Change requests carry reason |
| Document upload / preview / download | Yes (`document.uploaded`, `.previewed`, `.downloaded`) | n/a | n/a |
| Admission status change | Yes + dedicated `academic_admission_status_history` (27 rows) | Yes | Correction workflows require a justification |
| Announcement, support, import/export | Yes | Yes where meaningful | n/a |

**Verdict on institutional reliability:** adequate for accountability — *who did what, to which record, when, from where*. Not a complete change ledger: for ordinary student-profile edits and for class-grade edits the **prior values are not recorded anywhere**, so reconstructing "what was the phone number before this edit" requires a database backup, not the audit log. Where the institution most needs a reason and a before/after (absences, placements, admission status, account roles, housing transfers, examination corrections), it has one.

### D.4 Three findings worth acting on

| # | Finding | Severity | Evidence |
|---|---|---|---|
| D-1 | `audit_logs` is append-only **by application convention only**. The application never exposes an update or delete route, but the `portal` database role still holds `UPDATE` and `DELETE` on the table and no trigger prevents it. | **P2** | `has_table_privilege('portal','audit_logs','UPDATE'\|'DELETE')` → `true/true`; only foreign-key triggers exist |
| D-2 | Ordinary student-profile edits record changed **field names**, not old/new values. | **P2** | Live row: `context={"fields":["preferred_name"]}`, no values |
| D-3 | The class-grade create/update path logs identifiers only; prior score is preserved only on the examination correction path. | **P2** | `academic.py` audit contexts vs `examination.py:1499` `previous_score` |

None of these is a data-corruption defect, and none needs fixing before a baseline commit. They are the difference between "we can prove who changed this" and "we can prove what it was before".

### D.5 History tables and retention

Four dedicated history tables exist **and are written by application code**: `academic_admission_status_history` (27 rows in this database), `academic_change_history`, `student_original_admission_history`, `immigration_profile_versions`. The three empty ones are empty because this demo dataset has no admission changes, no original-admission corrections and no immigration edits — not because the write paths are dead (**VERIFIED** by locating each writer in `services/`).

**Retention policy: INSTITUTIONAL DECISION REQUIRED.** `RETENTION_*` is deliberately unset, so the retention report answers "policy pending approval" and nothing may be deleted or archived. No retention period has been invented anywhere in this assessment.

---

## E. Authentication and session assessment

| Check | Result | Evidence |
|---|---|---|
| Sign-in for admin / management / teacher / student | **VERIFIED** | 4/4 accounts `login=200 me=200` on a fresh database (Phase 8) |
| First-login password change, temporary credentials | **VERIFIED** | Suite + `c4d7e91b2f68` migration; `must_change_password` honoured |
| Admin-assisted reset | **VERIFIED** | `test_admin_password_reset.py` in the 1,059-test run |
| Logout invalidates server-side | **VERIFIED** | Browser scenario 8 replays the pre-logout cookie → rejected |
| Session persistence across navigation and refresh | **VERIFIED** | Scenarios 2–3 |
| Multiple tabs share one session | **VERIFIED** | Scenario 3, and soak's second tab |
| A single `401` does not end a valid session | **VERIFIED** | Scenario 5 |
| Transport failure is not treated as expiry | **VERIFIED** | Scenario 4 |
| Dead session → exactly one redirect with an explanation | **VERIFIED** | Scenario 7 |
| Role change / deactivation invalidates access | **VERIFIED** | Suite; `account.sessions_revoked` path present |
| Survives API or frontend restart | **VERIFIED** | Session rows are in PostgreSQL; restart proof in Phase 8 |
| Cross-origin mutation refused | **VERIFIED today** | `403` with `Origin: https://evil.example` |
| Alerting on mass failed logins | **NOT VERIFIED** | No monitoring export |
| Rate limiting under production settings | **NOT VERIFIED** | The load run used `rate_limit_enabled: false` |

**Supported duration:** a **60-minute sustained authenticated session** — 57 cycles, **0 session failures**, 2 transport aborts (`ERR_EMPTY_RESPONSE` from the Next dev server under a 3.8 GiB memory cap shared with a build and the full suite), both classified separately and neither ending the session.

**Browser support:** Chromium is certified end to end (10/10 + soak). **WebKit** has a 27-test authentication subset only. **Firefox cannot launch on this host** ("Could not find profile folder", macOS 27.2.1) — an environment limitation, not an application finding.

---

## F. Security assessment

No formal OWASP ASVS 5.0 / API Top 10 certification was performed and none is claimed. This is a control-by-control reading of what exists, tested or not.

### F.1 Verified controls

| Control | Result |
|---|---|
| Password storage | bcrypt hashes; `password123` is rejected after fresh initialisation with the new credential (**VERIFIED**) |
| Session token storage | Opaque server-side row; cookie `HttpOnly; SameSite=Lax`; `Secure` enforced in production (**VERIFIED** in rehearsal) |
| CSRF / origin | Single ASGI middleware; trusted origins from `CORS_ORIGINS`, never from `Host`/`X-Forwarded-*`; cross-origin mutation → `403` (**VERIFIED today**) |
| Authorization | Endpoint-level permission checks + object-scope checks; unauthenticated `/audit` → `401`; direct API access cannot exceed role (**VERIFIED**) |
| Sensitive-data redaction in logs/audit | Recursive denylist at write time (**VERIFIED** in source) |
| File scanning | Real ClamAV 1.5.4: clean → `201 CLEAN`; scanner down → `503 SCANNER_UNAVAILABLE`, file never stored (**CARRIED**) |
| Document integrity | `checksum_sha256` per document, 14/14 matching (**VERIFIED today**) |
| HTTP → HTTPS | `308` redirect (**CARRIED**) |
| TLS | Caddy with a real certificate path exercised in the production rehearsal (**CARRIED**) |
| Production debugging exposure | `DEBUG` off, docs not served, no `.env` or source in the web image (**CARRIED**) |
| Dependency posture | No frontend DB driver, no unexplained dependency additions in this diff (**VERIFIED**) |

### F.2 Known gaps

| # | Gap | Severity | Note |
|---|---|---|---|
| F-1 | **No ClamAV service in the production composition.** `MALWARE_SCANNER=disabled` fails closed, so document upload does not work in production until an endpoint is supplied. | **P0 (production)** | Compose now forwards `CLAMAV_HOST/PORT/TIMEOUT`; only the service/endpoint decision is missing |
| F-2 | **EICAR cannot prove embedded-payload detection.** The official signature matches the whole file, so a PDF *containing* the EICAR string is reported clean. Detection must be proven with a custom signature set or a real sample. | **P1 (verification method)** | Documented honestly rather than papered over |
| F-3 | **`audit_logs` not immutable at the database level** (finding D-1). | **P2** | Requires DB access to exploit; no application route exists |
| F-4 | **No monitoring, alerting or log aggregation.** Failed-login bursts, 5xx spikes and disk exhaustion are invisible until a user reports them. | **P1 (operations)** | Carried from the production-readiness certification (AMBER) |
| F-5 | **Brute-force protection not verified under production settings.** The load harness disabled rate limiting. | **P2** | Re-verify on the university server |
| F-6 | **No off-host backup destination.** A backup beside the server it protects is not a backup. | **P1 (operations)** | See §I.5 |
| F-7 | **Firefox unverified; WebKit partially verified.** | **P2** | Host limitation |

**Sensitive data position:** passport, residence-permit and identity data are role-gated, redacted from audit contexts, never written to the audit log, and reachable only through controlled document endpoints with per-download audit rows. They are **not** encrypted at the application layer — protection depends on PostgreSQL and volume permissions, which is normal but must be stated as an assumption, not a guarantee. Nothing in this assessment establishes legal or regulatory compliance.

---

## G. Capacity and performance assessment

### G.1 Planning model (assumptions, not claims)

The university has ~1,500 registered students plus teachers, management and admin. Total accounts and simultaneous users are different numbers.

| Scenario | Concurrent authenticated users | Rationale |
|---|---|---|
| Normal working day | 25–50 | ~2–3% of the student body plus staff |
| Busy period (enrollment, timetable publication) | 75 | Short bursts around a deadline |
| High activity (results release, registration day) | 150 | Optimistic peak |
| Stress exploration | 300 | Only if the host can take it |

### G.2 What was actually measured

The existing harness (`scripts/load/run_load.py`, `docker-compose.perf.yml`) was run on 2026-11-25 against an isolated stack on `:8010` with **4 API workers** and a database seeded to **1,500 users / 1,446 students / 1,446 enrolments / 1,760 attendance rows / 30 documents**. Workload: 60% student reads, 30% staff reads, 10% sensitive writes. 15 s per level, ramp-up included, `rate_limit_enabled: false`. No route, query or index changed since, so these numbers still describe this code (**CARRIED** with that justification).

| Profile | Concurrency | Throughput | Errors | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| Read-heavy | 10 | 91.9 req/s | 0.0% | 64 ms | **304 ms** | 428 ms | 657 ms |
| Read-heavy | 25 | 78.5 req/s | 0.0% | 253 ms | **840 ms** | 1,136 ms | 1,651 ms |
| Read-heavy | 50 | 80.5 req/s | 0.0% | 456 ms | **1,612 ms** | 2,261 ms | 3,167 ms |
| Write-heavy | 5 | 30.4 req/s | 0.0% | 147 ms | **404 ms** | 503 ms | 747 ms |
| Write-heavy | 10 | 43.0 req/s | 20.9%* | 202 ms | **570 ms** | 838 ms | 1,273 ms |
| Login | 40 sequential | 15.6 req/s | 0.0% | 2,034 ms | **2,295 ms** | 2,432 ms | — |

\* every one of the 137 "errors" is a `400` business-rule refusal (duplicate attendance for the same student and date), not a failure. Correct behaviour under concurrency.

**Resources at concurrency 25 (read-heavy):** API CPU peak **313.9%** of 400% available, API memory 554 MiB, database CPU 72.6%, database connections 23 (2–3 active). **The API is the bottleneck, not the database** — the database was almost idle at 2–3 active queries while the API saturated four workers.

**No 5xx errors occurred at any level.** Error rate for genuine failures: **0.0%** everywhere.

### G.3 Correctness under concurrency (measured)

| Race | Attempts | Outcome |
|---|---|---|
| Same bed, 3 beds × 12 claims | 36 | 3 successes, 33 × `409 BED_OCCUPIED` — one occupant per bed |
| Class capacity 1, 20 claims | 20 | 1 × `201`, 19 × `400` — capacity never exceeded |
| Duplicate attendance, 12 concurrent | 12 | 1 × `201`, 11 × `400`, **0 duplicate rows** |
| Concurrent immigration update, 10 | 10 | 10 × `200`, **10 history rows**, final state is one of the writes |
| Retired program-change write, 10 | 10 | 10 × `409` |

This is the strongest evidence in the assessment that business rules hold under load rather than only in sequence.

### G.4 Where the time goes

| Query | Calls | Total | Mean |
|---|---|---|---|
| `UPDATE user_sessions SET last_accessed_at = …` | 5,103 | 95.9 s | 18.8 ms |
| Attendance range select | 548 | 5.7 s | 10.3 ms (2.8 M rows scanned across calls) |

Session-touch writes dominate database time and scale with request count, not users. That is a known, bounded cost — not a leak.

### G.5 Capacity conclusion — stated precisely

| Claim | Status |
|---|---|
| 1,500 registered accounts | **VERIFIED** — seeded and exercised |
| 25 concurrent users | **VERIFIED** — p95 840 ms reads, 0 errors |
| 50 concurrent users | **VERIFIED** — p95 1.6 s reads, 0 errors; exceeds a 500 ms p95 target |
| 75 concurrent users | **ESTIMATED** — reasonable extrapolation; p95 likely 2–2.5 s on 4 workers |
| 150 concurrent users | **NOT VERIFIED** — never attempted |
| 300 concurrent users | **NOT VERIFIED** — never attempted |
| 1,500 *simultaneous* users | **Not claimed and not supported by any evidence** |

Against a 500 ms p95 target for ordinary reads, this configuration meets it **only up to roughly 15–20 concurrent users**; at 25 it is already at 840 ms. Because the limit is API CPU (313% of 400% at 25 users), the remedy is cores, not query tuning: **an 8-core API allocation is the minimum for a 75-user busy period, and 16 cores for a 150-user peak** (**ESTIMATED**). This must be re-measured on the university server; the host here is a laptop-class Docker VM with 3.8 GiB shared with two other stacks.

**Data growth (ESTIMATED):** 1,500 students over four years with attendance, grades, documents and audit is on the order of a few GB of database plus documents — small for PostgreSQL 16. Index coverage is good (150 foreign keys, 68 unique constraints, 14 partial/expression indexes, 0 tables without a primary key), so growth is not the risk; concurrency is. Session rows and audit rows grow fastest and are the first candidates for archival once retention is approved.

---

## H. Frontend / backend separation

| Question | Answer | Evidence |
|---|---|---|
| Does the frontend use documented API contracts? | **Yes.** 173 references to `/api/v1`; typed client in `src/lib/api.ts` | **VERIFIED** |
| Does the frontend access the database? | **No.** No database driver is imported anywhere in `apps/web` | **VERIFIED** |
| Are authorization and business rules enforced by the backend? | **Yes.** Retired writes refuse server-side; role checks are server-side | **VERIFIED** |
| Are permissions independent of UI visibility? | **Yes.** Hiding a menu item changes nothing; direct requests are still refused | **VERIFIED** — role-route browser check |
| Are errors predictable? | **Yes.** `{"error": {"code", "message"}}` with 216 codes, all translated | **VERIFIED** |
| Are response shapes undocumented? | Largely no — Pydantic response models define them; a few list endpoints are loosely typed | **VERIFIED** |
| Can UI changes be isolated? | **Mostly.** Layout, styling, copy, table/form composition and locale files are frontend-only | **VERIFIED** — today's changes touched only `apps/web` |
| Which changes need backend coordination? | Anything adding a field, filter, sort key, bulk action or permission; anything changing pagination semantics; any new locale-specific format the API produces | Design-level |

**Conclusion.** Frontend-only changes — visual, copy, layout, navigation grouping, component composition, non-API-driven interactions — are safe to make without touching the backend, and this phase demonstrated that pattern. Changes that require a new query, a new field, a permission, or a different error contract inevitably cross into FastAPI: not because of coupling, but because the contract is the boundary. **A UI-only change never requires a database migration**; a migration is required only when a new persisted concept is introduced, and none is proposed in this report.

**Fragility worth noting:** shared layout components and global styles have the widest blast radius (they affect every route). Route-level components are isolated. The account menu and the notification poll interact — which is why the certification drives the menu by pointer; that remains a small, contained fragility, not a defect.

---

## I. Database integrity and recovery

### I.1 Schema and migration state

| Item | Result |
|---|---|
| Alembic head (container) | `c4d7e91b2f68` (**VERIFIED**) |
| `alembic check` | "No new upgrade operations detected" (**CARRIED** — no model changed since) |
| Tables | 64, all with a primary key (**VERIFIED today**) |
| Foreign keys | 150, **0 unvalidated** (**VERIFIED today**) |
| `ON DELETE CASCADE` | 4 — deliberate, on dependent rows |
| Unique constraints | 68; **Check constraints** 59; partial/expression indexes 14 |
| Roles per user | exactly 1 in this dataset (**VERIFIED**) |
| Destructive operations in the new migrations | **none in `upgrade()`** — `c4d7e91b2f68` adds a column, a table and two indexes; its `drop_table`/`drop_column` appear only in `downgrade()` (**VERIFIED**) |

### I.2 Orphans and constraints

No orphaned rows were found in the checks performed via constrained relationships (all 150 foreign keys are validated, so orphans are structurally impossible on those paths). One housekeeping observation: the local document store holds **211 files while `documents` has 14 rows**, so ~197 unreferenced files remain from test runs — no garbage collection exists for the local backend (**P3**).

### I.3 Transaction behaviour

Audit rows share the transaction of the change they describe, so a failed operation cannot produce a success record (**VERIFIED** in source). Concurrency runs produced no duplicate attendance, no double-booked bed and no capacity breach (§G.3).

### I.4 Backup → restore rehearsal (performed today on the real dataset)

The scripts had never been exercised against a realistic dataset. They have now been, using the unmodified `scripts/backup.sh` and `scripts/restore.sh`, with the dev document store staged into a temporary volume so the scripts archived the true bytes.

```
backup.sh                              exit 0
  database  361,251 bytes (pg_dump custom format, 558 archive entries)
  storage   295 entries, SHA-256 manifest written

full-table parity, source vs restored
  64 tables source / 64 tables restored
  every per-table row count IDENTICAL
  alembic_version restored = c4d7e91b2f68

restore.sh latest                      exit 0
  digests: ok db + storage
  tables 64, alembic revisions 1
  students 28, users 31, documents 14
  missing objects 0, checksum failures 0
  live database not touched

cleanup: scratch databases dropped, probe volume removed
```

**VERIFIED:** the backup restores into an isolated scratch database with identical content; the SHA-256 manifest detects tampering; every document row's bytes exist and match its stored checksum; the live database is never touched by verification.

**Also carried:** the earlier production-shaped rehearsal restored a 1-student database through TLS with the same scripts (64 tables, 1 revision, 0 checksum failures). Today's run extends that from a trivial dataset to the full development dataset.

### I.5 Remaining recovery risks

| # | Risk | Severity |
|---|---|---|
| I-1 | **No off-host backup destination, no schedule, no retention.** The mechanism works; the operation does not exist yet. | **P1 (operations)** |
| I-2 | **No restore drill cadence.** Today's rehearsal is the first; it must become routine. | **P1 (operations)** |
| I-3 | **RPO/RTO unagreed.** Technical estimate: a 361 KB dump restores in seconds; at institutional scale expect minutes for the database plus document transfer time. Committing to numbers is **INSTITUTIONAL DECISION REQUIRED**. | Institutional |
| I-4 | Database and document store are backed up separately, so a restore must apply both to keep document rows and bytes aligned. The script verifies alignment; the procedure must state it. | **P2 (documentation)** |

---

## J. Local-server deployment assessment

Three distinct configurations, because they fail differently.

### J.1 Development machine (today)

Docker Desktop capped at 3.824 GiB shared with the V1 stack. This is the direct cause of every "random" failure seen across phases: the Next dev compiler has been OOM-killed, and the two soak aborts were `ERR_EMPTY_RESPONSE` under memory pressure. Nothing here indicates an application defect.

### J.2 University server on the campus LAN (the realistic target)

**Access reality, stated plainly:** a LAN-only deployment **will not be reachable from outside the university network**. Staff working from home, applicants abroad and anyone on mobile data will get nothing. If remote access is required it must be designed deliberately — a VPN, or a public reverse proxy with a real certificate — and it is a separate decision with separate security consequences.

**Recommended shape**

```
university LAN
  clients ──HTTPS──▶ Caddy (443, institutional certificate)
                        ├── /        → web  (Next.js standalone, production image)
                        ├── /api/v1  → api  (uvicorn, --proxy-headers, forwarded-allow-ips = compose subnet only)
                        └── /docs    → not served
                     PostgreSQL 16  (no host port published; compose-internal only)
                     documents volume (host path or volume, 0600)
                     ClamAV (host or sidecar)  ← required before uploads work
```

**Hardware**

| Tier | Spec | Basis |
|---|---|---|
| Minimum viable | 4 vCPU, 8 GB RAM, 100 GB SSD | Runs; p95 degrades above ~25 concurrent users (measured) |
| Recommended | 8 vCPU, 16 GB RAM, 250 GB SSD, UPS | Meets a 75-user busy period with headroom (**ESTIMATED** from §G) |
| Headroom for peaks | 16 vCPU, 32 GB RAM | 150-user peaks (**ESTIMATED**, not measured) |

Storage: a few GB for four years of records and documents (**ESTIMATED**); 250 GB leaves room for documents, backups and growth.

**Operational requirements that are not yet in place**

| Requirement | Status |
|---|---|
| Automatic restart (`restart: unless-stopped`) | Present in compose |
| Health checks (`/health`, `/ready`) | Present |
| HTTPS + certificate renewal ownership | **INSTITUTIONAL DECISION REQUIRED** (ACME vs institutional CA) |
| DNS / hostname | **INSTITUTIONAL DECISION REQUIRED** |
| Firewall: only 443 exposed; DB never published | Must be configured on the host |
| `PROD_NETWORK_SUBNET` set to a free range | **Required** — the rehearsal failed once on a subnet collision |
| Off-host backup destination + schedule | **Missing** |
| Monitoring, alerting, disk-capacity watch | **Missing** |
| UPS / power protection | **INSTITUTIONAL DECISION REQUIRED** |
| Update procedure (OS, images, dependencies) | **Missing as a written procedure** |

### J.3 Internet-facing deployment

Adds public exposure of passport and identity data. Not recommended without a security review, WAF/rate limiting at the edge, and an incident-response owner. No evidence in this assessment supports it.

### J.4 What carries over from this machine, and what must be re-verified

**Carries over:** application correctness, permission enforcement, session semantics, schema and migrations, backup/restore mechanics, algorithmic capacity behaviour.
**Must be re-measured on the server:** latency at every concurrency level, actual core count, disk I/O, TLS termination cost, and the whole production composition end to end.

---

## K. Outstanding blockers

Only genuine blockers, split by who can close them.

### K.1 Technical (engineering can close)

| # | Blocker | Why it blocks | Severity |
|---|---|---|---|
| K-1 | **Fail-closed guard in `alembic/env.py`** refusing any database whose name is not `school_portal_v2` / `school_portal_test*` | One host-virtualenv command currently targets V1's database. A one-line mistake could migrate the reference installation | **P1** |
| K-2 | **Production-shaped rehearsal repeated with the current tree** (Caddy + HTTPS + secure cookie + both services behind the proxy) | It ran once, against a 1-student database, before the current tree. Secure-cookie and origin behaviour are exactly what production changes | **P1** |
| K-3 | **Backup automation and off-host destination** | A working script that nobody runs is not a control | **P1 (operations)** |
| K-4 | **Monitoring/alerting and disk-capacity watch** | Silent failure is the default today | **P1 (operations)** |
| K-5 | **Firefox and full WebKit certification** | Only Chromium is certified end to end | **P2** |

### K.2 Institutional decisions (engineering cannot close)

| # | Decision | Blocking what |
|---|---|---|
| K-6 | **Retention periods** for graduated, withdrawn, inactive, documents, audit | Reports say "policy pending"; nothing may be deleted or archived |
| K-7 | **Malware scanner endpoint** — external ClamAV or a `clamav` service in the production composition | Document upload does not work in production |
| K-8 | **TLS strategy, domain/DNS and certificate ownership** | Any HTTPS deployment |
| K-9 | **Admission phase gates for UAT** (`ADMISSIONS_WRITE_ENABLED`, `ADMISSION_CHANGE_REQUESTS_ENABLED`, …) | Which workflows UAT tests today depends on which compose file was used |
| K-10 | **Named UAT accounts** instead of the shared demonstration password | UAT cannot use a credential printed on a login screen |
| K-11 | **Email relay** — yes or no | Notification mail and optional self-service reset |
| K-12 | **RPO/RTO and off-host backup target** | Any recovery commitment |
| K-13 | **Real-data migration authorisation and data copy** | Everything in §M's migration row |

**P0 by the brief's strict definition (critical security, data corruption, system-breaking): none.** Every item above either blocks going live with real data or is an operational control, not a defect in the running application.

---

## L. Commit readiness

### L.1 Tree state (verified)

| Check | Result |
|---|---|
| Branch / HEAD | `main` / `8467300` |
| Changes | 54 modified, 50 untracked, **0 deleted, 0 staged, 0 stashes** |
| Diff size | 1,265 insertions, 357 deletions |
| Binary or asset changes | **none** |
| Secret-like literals added | **none found** in the tracked diff |
| `.env`, `.env.*`, `.demo-credentials.json`, `.perf/`, `var/` | all git-ignored (**VERIFIED** with `git check-ignore`) |
| Untracked files | all classified below; no unexplained artefacts |
| Destructive migration in `upgrade()` | none |
| V1 touched | **no** |

### L.2 Change classification

| Class | Files | Notes |
|---|---|---|
| **1. Required application fixes** | 19 `apps/api/app/*` (auth, settings, seed, main, models, users, account, notification), 11 `apps/web/src/*` (login, api client, auth context, auth guard, app shell, data table, card, lightbox, i18n request) | Credential single-source fix, origin middleware, session stability, mail outbox, accessibility fixes |
| **2. Required tests** | 9 `apps/api/tests/*`, 15 `apps/web/e2e/*` | Demo-credential drift guard, origin guard, admin reset, email delivery, session stability, Phase 8 certification, accessibility |
| **3. Documentation** | 10 `docs/*` | Assessment, remediation, functional certification, production readiness, presentation readiness, change impact, baseline, Phase 8, roadmap, this report |
| **4. Build / deployment** | 5 `infra/*`, 4 compose files, `Makefile`, `.github/workflows/ci.yml`, `.dockerignore`, `infra/docker/.dockerignore`, `Dockerfile.api`, `Dockerfile.web`, Caddyfiles | Production composition, images, CI, scanner forwarding |
| **5. Existing developer work to preserve** | 8 `scripts/*`, 5 `apps/web/scripts/*`, `apps/api/tools/seed_load.py`, 5 `apps/web/messages/*`, `next.config.ts`, `package.json`, `pnpm-lock.yaml`, `playwright.config.ts`, `.env.example`, `.env.production.example`, `.gitignore`, 2 alembic versions | All intentional; none should be discarded |
| **6. Unexplained or risky** | **none** | Every path maps to a documented phase |

### L.3 Recommended grouping

1. **Backend:** credential single-source (`settings.py`, `seed.py`, `seed_demo_full.py`, `main.py`), origin middleware, session/account/mail changes, and their tests.
2. **Frontend:** login page, API client, auth context/guard, layout and UI component fixes, locale files.
3. **Deployment & CI:** compose files, Dockerfiles, Caddyfiles, Makefile, workflow, env templates, dockerignores.
4. **Scripts & tooling:** backup, restore, demo up/down, e2e, load, certification, demo accounts.
5. **Docs:** the report set, including this one.
6. **Migrations:** `b8d2f4a61c93` (index rename) and `c4d7e91b2f68` (temporary credentials + email outbox) — additive upgrade, no data loss.

**Do not commit:** `.env`, `.env.rehearsal`, `.demo-credentials.json`, `.perf/`, `apps/api/var/`, `backups/`, any `node_modules`, and the `/tmp` rehearsal artefacts. All are already ignored except the last, which is outside the repository.

### L.4 Verdict

**GO to commit as a stable baseline.** The tree is internally consistent, builds, passes 1,059 backend tests and type-checks, carries no secrets, has an additive migration path and contains no unexplained change. Committing is not what is missing — deployment rehearsal and institutional decisions are.

---

## M. Final functionality status

| Dimension | Classification | One-line justification |
|---|---|---|
| Development stability | **STABLE** | Full suite green, types clean, migrations consistent, reproducible credential path |
| Internal presentation stability | **STABLE** | Fresh init works; 144/144 pages build; 24/24 pages exercised previously; 60-min soak |
| Functional completeness | **COMPLETE for the defined workflows** | 22 routers all have a UI surface; no "coming soon" navigation; no `TODO`/`FIXME`/`NotImplemented` in shipped code |
| Historical/audit reliability | **ADEQUATE, not a full ledger** | Who/what/when/where reliable and verified live; prior values missing for ordinary profile edits and class grades |
| Authentication/session stability | **CERTIFIED (Chromium)** | 10/10 scenarios, 57-cycle soak, 0 session failures; Firefox/WebKit incomplete |
| Security readiness | **GOOD FOUNDATION, NOT ASSESSED TO A STANDARD** | Strong authorization, origin, scanning and redaction controls; no formal ASVS certification; audit table not immutable; no monitoring |
| 1,500-student capacity confidence | **HIGH for 1,500 accounts; MODERATE for 50 concurrent; LOW above 75** | Measured at 10/25/50 with 0% failure; API CPU-bound; 150 and 300 untested |
| Institutional UAT readiness | **CONDITIONAL GO** | Needs named accounts, a production build and a gate decision — all non-code |
| Local-server operational readiness | **NOT READY** | Working components; no deployment has run, no backup automation, no monitoring, no UPS/update procedure |
| Production readiness | **NOT READY** | Scanner endpoint, retention, TLS/domain ownership and a current-tree rehearsal all open |
| Real-data migration readiness | **NOT READY** | Reconciliation paths tested on synthetic data only; no rollback exercise on real data |

---

## N. Recommended next steps

Only what is necessary, in order. No new features.

### Technical, in priority order

1. **`alembic/env.py` fail-closed guard** (K-1) — one small change, removes the only path by which this project could damage V1. Run the relevant migration tests afterwards.
2. **Repeat the production-shaped rehearsal with this exact tree** (K-2): Caddy, HTTPS, secure cookie, `PROD_NETWORK_SUBNET` set, real ClamAV, both services behind the proxy, then a backup and restore from inside that stack. Exit criterion: sign-in, one document upload and one restore all succeed over TLS.
3. **Backup automation + off-host destination + a written restore procedure** (K-3, I-4). The mechanism is now proven; schedule it and store it somewhere else.
4. **Monitoring and disk alerts** (K-4) — a metrics or log endpoint plus one alert on 5xx rate and one on disk usage. Without it, everything else is trust.
5. **Firefox and full WebKit certification** (K-5) on a host where they launch.

### Institutional, before any real data

6. **Retention values** (K-6) — approve `RETENTION_*`; nothing may be archived until then.
7. **Scanner endpoint** (K-7) — decide external daemon or sidecar service; uploads are blocked until this exists.
8. **TLS/DNS/certificate ownership and renewal** (K-8).
9. **UAT accounts and admission gate configuration** (K-9, K-10) — named accounts per role and office, and a written statement of which gates are open.
10. **Email relay decision** (K-11) — either way, record it.
11. **RPO/RTO** (K-12) — then automation, not before.

### Then, and only then

12. **Real-data migration rehearsal with rollback** on a copy of institutional data, through the existing reconciliation workflows.

### Deliberately not proposed

No schema change, no refactor, no UI redesign, no new module, no rewrite of admission, housing, immigration or examination. The three audit findings (D-1, D-2, D-3) are documented for a future decision; none blocks a baseline commit, and fixing them changes audit semantics, which deserves its own review rather than a quiet edit.

---

## Appendix 1 — Evidence produced during this assessment

| # | Check | Result |
|---|---|---|
| 1 | Git state | `main` @ `8467300`; 54 modified, 50 untracked, 0 deleted, 0 stashes |
| 2 | Diff classification | 1,265+/357−; 0 binary; 0 secret-like literals; all paths classified |
| 3 | Referential integrity | 150 FKs, 0 unvalidated, 68 unique, 59 check, 0 tables without PK |
| 4 | Migration safety | head `c4d7e91b2f68`; destructive calls only in `downgrade()` |
| 5 | Live audit round-trip | `student.updated` row with correct actor, entity, timestamp, IP, context |
| 6 | Audit duplication | 2 changes → exactly 2 rows |
| 7 | Audit access control | no cookie → `401`; cross-origin PATCH → `403` |
| 8 | Audit immutability | no trigger; `portal` role holds UPDATE/DELETE — **finding D-1** |
| 9 | Document byte integrity | 14/14 rows present and checksum-matched |
| 10 | Backup | `backup.sh` exit 0; 361,251-byte dump; 295-entry storage archive |
| 11 | Restore parity | 64/64 tables, **all row counts identical**, alembic head restored |
| 12 | Restore verification | `restore.sh` exit 0; 0 missing objects; 0 checksum failures; live DB untouched |
| 13 | Localization | 2,567 keys × 5 locales; 145 dynamic keys; 216 error codes — exit 0 |
| 14 | Frontend DB independence | no database driver imported in `apps/web` |
| 15 | Capacity | measured at 10/25/50 concurrent, 1,500 seeded accounts, 0% genuine errors |

## Appendix 2 — Not run, and why

| Area | Status | Reason |
|---|---|---|
| Full backend suite | **CARRIED** (1,059 passed / 2 skipped) | No application code changed since that run; today's work was verification and one report |
| `next build` / `tsc --noEmit` | **CARRIED** (144/144 pages; exit 0) | No source change since |
| Browser certification | **CARRIED** (10/10) | No source change since |
| 60-minute soak | **CARRIED** (57 cycles, 0 failures) | No source change since |
| Concurrency 150 and 300 | **NOT VERIFIED** | Not attempted; host cannot support it alongside other stacks |
| Firefox | **NOT VERIFIED** | Browser cannot launch on this host |
| Full WebKit suite | **NOT VERIFIED** | Only a 27-test authentication subset exists |
| Production composition on a real host | **NOT VERIFIED** | Only the isolated TLS rehearsal; no deployment |
| Real-data migration | **NOT VERIFIED** | Out of scope; no approved data copy |
| SMTP over a real relay | **NOT VERIFIED** | No relay configured |
| Rate limiting under production settings | **NOT VERIFIED** | Disabled in the load harness |
| Formal OWASP ASVS / API Top 10 assessment | **NOT PERFORMED** | Not claimed anywhere in this report |

## Appendix 3 — Disclosures

- **Data touched:** one admin `PATCH` on `STU-001.preferred_name` (empty → `AuditProbe` → empty). The value was restored exactly; **two** audit rows were added to the development audit log, which is the correct and permanent record of those two real administrative actions. No other row was modified.
- **Scratch resources created and removed:** `school_portal_restore_parity` (dropped), `sycumain-v2-docstore-probe` (volume, removed), `school_portal_restore_verify` (dropped by `restore.sh`), `/tmp/v3-backup-rehearsal` (outside the repository).
- **Untouched:** V1 stack and database, the development database contents, all existing migrations, all five locale files, every untracked file.
- **Not done:** no commit, no stage, no push, no deploy, no real-data migration, no schema change.

---

*End of report.*
