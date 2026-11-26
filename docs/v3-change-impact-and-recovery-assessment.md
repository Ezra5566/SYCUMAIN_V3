# SYCUMAIN V3 — Change Impact Assessment, Development Recovery & Stability Restoration

**Date:** 2026-11-25
**Scope:** V3 (`SYCUMAIN_V2`, web 3101 / api 8001 / db 5435) investigated after the Phase 6/7 and presentation-readiness modification waves.
**Mode:** investigation first. **No product code was modified.** The only file written is this report. No commit, no push, no deployment, no migration run, no database write, no V1 change.

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **[V]** | Verified in this session, by a command whose output is quoted in §E. |
| **[C]** | Previously certified in a named document on the same tree; **not** re-run now, and not presented as a current result. |
| **[N]** | Not tested in this session. |

---

## A. Executive summary

**What the current state is.** V3 is `main` at `8467300` ("feat: activate migrated accounts instead of issuing passwords") with a large, coherent, entirely uncommitted working tree: **52 modified tracked files, 44 untracked files, 0 deletions, 0 renames, 0 stashes, 0 conflict markers [V]**. The changes are one continuous wave on 2026-11-25 (file mtimes 04:53 → 13:47), all documented across the Phase 6, Phase 7 and presentation-readiness reports. There is no evidence of divergent parallel edits or of an in-flight merge.

**Stability.** The stack is healthy and idle-stable: api `200` (uptime 10,942 s), web `200`, postgres healthy, Alembic at head `c4d7e91b2f68` **[V]**. On the **current** tree, not a historical one: the full backend suite is **1,052 passed, 2 skipped, 0 failed** in 15:53 **[V]**, TypeScript is clean **[V]**, the five-locale translation parity check passes **[V]**, and `alembic check` reports *no new upgrade operations* **[V]**, meaning model metadata and migrations now agree.

**What the waves actually changed.** Almost nothing in the institutional domain. The modifications are (i) the authentication lifecycle and its security controls, (ii) a global CSRF/origin guard, (iii) administrator-assisted credential hardening plus an optional SMTP channel with a durable outbox, (iv) accessibility and i18n corrections, and (v) build, packaging, deployment and test-harness repair. **No academic, housing, immigration, enrollment, timetable or document-authorisation business rule was altered**; the only schema change is one nullable column on `users`, one new `email_outbox` table and one index rename, all additive and reversibility-tested by design.

**Are the prior reports still accurate?** Mostly yes, with four stale statements — and the four most alarming defects they recorded **are now closed**: `next build` and `tsc` failures, the broken production compose file, the `alembic check` drift, and the missing browser harness. Each is re-verified as fixed in §E. The stale statements are catalogued as R-7.

**The one defect worth fixing next** is not new: the demonstration password now exists in exactly **one** place (`login/page.tsx`), while `password123` still appears **107 times** across seeders, fixtures, tests and scripts **[V]**. The demo database was rotated by hand, so the demo works today; a fresh seed would silently reinstate the exact defect that produced the reported "login loop". That is a *recurrence path*, not a current failure.

**Verdicts.** Continued development: **GO**. Internal demonstration: **GO**. Institutional UAT: **GO to begin**, conditional. Technically production-ready: **NO-GO**. Real institutional data migration: **NO-GO**.

---

## B. Change inventory

Counts are exact (`git status --porcelain -uall`) **[V]**. Generated artifacts (`.next`, `node_modules`, `dist`, `.perf/`, `var/`) are excluded; none is counted as a source modification.

### B.1 Committed baseline

| Item | Value |
|---|---|
| Branch / HEAD | `main` / `8467300` |
| Last five commits | `8467300` activate migrated accounts · `adfea31` importers agree on who a student is · `be3b24f` housing allocations under preview/confirmation · `f8ad3e2` preview documents, mobile navigation · `30fa654` put the SCU portal under version control |
| Working tree | 52 modified (**M**), 44 untracked (**??**), 0 deleted, 0 renamed, 0 stashed |

### B.2 Significant modifications, grouped

| # | Area | Files | Nature of change | Functional impact | Risk | Evidence |
|---|---|---|---|---|---|---|
| 1 | **Session security** | `api/app/config/settings.py`, `api/app/auth/dependencies.py` | Cookie renamed `session_token` → `sycumain_session`; the name is now read from settings, not restated | Ends mutual session destruction between V1 (`:8000`) and V3 (`:8001`) on host `localhost` — cookies ignore port. This was the root of "logged in but everything says not authorised". | One-time sign-out of every existing session (expected). Any code/doc still naming the old cookie is stale. | [V] config + live login |
| 2 | **Session performance** | `api/app/auth/service.py` | `last_accessed_at` written at most once per minute; naive timestamps treated as stale instead of raising | Removes a DB write (and a per-user row lock) from every authenticated request — the top find in the Phase 7 load test (18.8 ms mean, 5,103 calls/run) | Expiry is governed by `expires_at` and untouched; only the "active sessions" telemetry is minute-granular | [V] suite green |
| 3 | **Frontend session lifecycle** | `web/src/lib/api.ts`, `lib/auth-context.tsx`, `components/auth/auth-guard.tsx` | `resolveApiBase()` (no hard-coded `localhost:8000`), `SESSION_ENDED_EVENT` on authoritative `401 UNAUTHORIZED`, probe-path exclusions, 3-attempt mount restore, single-flight re-check, transport failure no longer signs out, retry UI instead of login screen | Removes the "must log out and back in before components work" symptom; prevents a network blip from destroying a valid session; keeps client state consistent with server-side revocation | Highest blast radius in the change set (every fetch, root provider). Fully covered by the suite and `auth-stability.spec.ts`. | [V] tsc 0, suite green |
| 4 | **CSRF / origin guard** | `api/app/core/origin.py` (new), `api/app/main.py`, `settings.py` | Middleware rejects `POST/PUT/PATCH/DELETE` whose `Origin` is not in `trusted_origins` (derived from `CORS_ORIGINS`); `Origin: null` rejected; missing `Origin` allowed only if `Sec-Fetch-Site` ≠ `cross-site` and any `Referer` is same-origin; `Host` never trusted | Adds an application-level decision to a protection that previously rested only on `SameSite=Lax`. Rejection is `403 CSRF_ORIGIN_REJECTED` before routing, auth or any DB work | Global middleware: a mis-configured origin list breaks **every** unsafe request. Production validator now refuses wildcard/`null` origins. | [V] live probes: foreign `403`, both local origins accepted |
| 5 | **Admin-assisted recovery hardening** | `api/app/models/identity.py`, `services/account.py`, `auth/router.py`, `routers/users.py`, `auth/{activation,recovery}.py` | `users.temporary_password_expires_at`; login refuses an expired temporary credential (`403 TEMPORARY_PASSWORD_EXPIRED`) **after** credential verification and **before** session creation; deadline cleared on self-change/activation/reset | Makes the V1-style counter-issued password time-limited as well as single-use-in-effect. Legacy rows with `NULL` deadline are not locked out and are still trapped behind `must_change_password` | Additive nullable column; no existing row rewritten. Existing sessions are revoked on reset, so an expired credential cannot linger in a live session. | [V] migration applied, schema inspected |
| 6 | **Email delivery (optional)** | `api/app/models/mail.py` (new), `services/mailer.py` (new), `services/notification.py`, `auth/router.py`, `routers/users.py`, `cli.py` | `email_outbox` with unique `dedupe_key`, bounded retries with backoff, `FOR UPDATE SKIP LOCKED` flush, masked logs, `python -m app.cli send-emails`; reset/activation links sent inline and **never** stored | Operational notification email without an in-process background task; a mail outage cannot roll back a business transaction | Disabled by default (`EMAIL_ENABLED=false`, `EMAIL_NOTIFICATIONS_ENABLED=false`); production validator refuses `smtp` without host/enabled. Body deliberately carries no case detail. | [C] real-SMTP certification; [V] imports clean |
| 7 | **Academic model hygiene** | `api/app/models/examination.py` | Removed a `UniqueConstraint(examination_id, class_section_id)` that duplicated the composite primary key | Makes metadata agree with the database and removes a would-be redundant index | None; uniqueness still enforced by the PK | [V] `alembic check` clean |
| 8 | **Demo dataset** | `api/app/seed_demo_full.py` | Student index `0` (`STU-001`, the account every demo signs in as) left unverified and blank instead of verified | Makes the student-initiated immigration renewal workflow demonstrable end to end | Demo-only; no business rule changed | [C] presentation rehearsal |
| 9 | **Localisation** | `web/messages/{en,zh,fr,ru,ar}.json`, `web/src/i18n/request.ts`, `next.config.ts` | 3 new error codes × 5 locales (`TEMPORARY_PASSWORD_EXPIRED`, `EMAIL_DELIVERY_FAILED`, `CSRF_ORIGIN_REJECTED`), 2 audit labels × 5; static message map replaces dynamic import | Users see a cause, not a generic failure, for the three new refusal paths | Parity is machine-checked; a missing key fails the check | [V] 2,567 keys × 5, 216 codes, pass |
| 10 | **Accessibility** | `components/ui/{card,data-table,image-lightbox}.tsx`, `app-shell.tsx`, `students/page.tsx`, `app/loading.tsx`, `login/page.tsx` | `h3`→`h2`, table accessible name, non-empty select-all header, account-menu focus restore, localised lightbox labels and loading text, `aria-invalid`/`aria-describedby` on rejected login | WCAG 2.2 AA items closed without visual redesign | Low; component-level only | [C] 11/11 on two browsers; [V] tsc 0 |
| 11 | **Login page** | `web/src/app/[locale]/login/page.tsx` | `DEMO_PASSWORD = "Sycumain2026!"` beside `DEMO_ACCOUNTS`; chips fill it; expired-session notice; error wiring | Restores one-click demo sign-in (the chip previously filled `password123` against rotated accounts, guaranteeing a 401 that looked like an auth fault) | **Source of truth duplicated** — see R-1. Chips are gated by `NODE_ENV !== "production"` **[V]**. | [V] live end-to-end login |
| 12 | **Build / packaging** | `web/package.json` (Next pinned `15.5.29`, `pnpm.onlyBuiltDependencies`), `next.config.ts`, `.dockerignore`, `infra/docker/*`, `docker-compose.{yml,prod,test,perf}.yml`, `Caddyfile{,.local}` | Next.js security upgrade; single-argument `createNextIntlPlugin`; standalone output; three isolated stacks (dev 3101/8001/5435, test 3002/8002/5436, prod behind TLS) | A producible, deployable artifact and a test stack that cannot touch dev data | Production compose requires a populated env file (correct, but `config` fails loudly without one) | [V] prod compose validates with the example env; [C] image build |
| 13 | **Test harness** | `web/playwright.config.ts`, `e2e/*.spec.ts`, `e2e/accounts.ts`, `docker-compose.test.yml`, `scripts/e2e.sh`, `api/tests/*` | `E2E_BROWSERS` selection; `signOutViaAccountMenu` helper; isolated e2e stack; new specs `auth-stability`, `accessibility`; new API suites `test_session_stability`, `test_origin_guard`, `test_email_delivery`, `test_admin_password_reset` | Regression cover for exactly the defects in this wave | Harness only | [V] 1,052 API tests pass |
| 14 | **Operations** | `Makefile`, `.github/workflows/ci.yml`, `scripts/{backup,restore,demo-up,demo-down}.sh`, `scripts/demo_accounts.py`, `scripts/load/run_load.py`, `scripts/certification/permission_matrix.py` | Backup/restore with checksum manifest and scratch-DB verification; demo lifecycle with route pre-warm; credential rotation; load runner; permission matrix | Makes the system reproducible and demonstrable | Scripts are untracked but git-ignored artifacts are excluded (`.perf/`, `.demo-credentials.json`) | [C] backup/restore rehearsal |

**Not to be treated as source modifications:** `.perf/` (screenshots, soak/permission/walkthrough JSON, rehearsal backups), `.demo-credentials.json` (mode 0600, git-ignored, absent from `git status` **[V]**), `apps/api/var/`, `dist/`, `node_modules/`, `.next/`.

### B.3 Migrations

| Revision | Purpose | Data risk |
|---|---|---|
| `b8d2f4a61c93` | Rename `ix_immigration_reminders_profile_id` → `…_immigration_profile_id` | Metadata-only. Idempotent (skips if either name state already holds). No row read/reordered. |
| `c4d7e91b2f68` (head) | `users.temporary_password_expires_at` (nullable); create `email_outbox` + 2 indexes | Purely additive. Existing rows `NULL`. Downgrade drops only the column and delivery history. |

Both are applied on the development database (`alembic_version = c4d7e91b2f68`) **[V]**, and the objects exist (column `timestamp with time zone null=YES`, `email_outbox` present, renamed index present) **[V]**.

---

## C. Production impact by domain

**Security.** Net improvement, with one residue. The origin guard converts a browser-default-only defence into an application decision; `Origin: null` is refused; wildcard/`null` origins are refused at startup; the temporary credential is now time-limited; email bodies carry no case detail and logs mask recipients. The residue is the demo password literal in the login page: it is compile-time gated by `NODE_ENV`, but I did **not** inspect a production bundle to prove the constant is absent from the shipped JS **[N]** — see R-1/R-5.

**Authentication.** The lifecycle now satisfies the required behaviour: valid sessions persist across navigation and refresh **[V]** (live login + reload in prior certification, and the 65-minute soak [C]); transport failures no longer clear the user; a genuine `401` produces one re-check and one controlled redirect; explicit logout clears local state even if the server call fails, with a bounded retry; backend authorization is unchanged and never bypassed by the client. No permanent/insecure session was introduced: `Max-Age=604800`, `HttpOnly`, `SameSite=lax`, `Secure` in production.

**Data integrity.** Unaffected by this wave. No model change touches housing, enrollment, attendance, immigration or documents; the only ORM edit removes a redundant constraint, and `alembic check` is clean. The transactional guarantees the brief names (bed assignment, enrollment capacity, no double allocation, no lost immigration update) were proven under concurrency in Phase 7 [C] and are not in the changed set.

**Academic operations.** Unchanged. Periods, intakes, offerings, sections, enrollments, timetables, program-change approval and the "future admissions may be prepared but not activated early" rule have no modification here. The one academic-adjacent edit is the exam-section constraint removal, which strengthens model/DB agreement rather than altering behaviour.

**Housing / Immigration / Documents.** No logic change. Indirect exposure only: these endpoints resolve the authenticated principal through the changed session path, so object-level authorisation is worth one smoke pass per role — done previously [C], not re-run now [N].

**Deployment and recovery.** Materially better: separate dev/test/prod files, TLS at the edge, API not published, migrations behind an explicit `tools` profile and never on boot, backup/restore with checksum verification and cold-restart recovery proven [C]. Remaining gaps are operational: single API worker, no metrics/alerting/log aggregation, local-only backup target, no CSP, and institutional decisions (mail provider, origins, TLS strategy, retention, RPO/RTO) still open.

---

## D. Regression findings

### R-1 — Demonstration password has two sources of truth — **P1**

**Severity:** P1 (production-hygiene; recurrence risk to the demo).
**Evidence [V]:** `Sycumain2026!` occurs in exactly one file (`apps/web/src/app/[locale]/login/page.tsx:32`); `password123` occurs **107 times** in 20+ files, including `apps/api/app/seed.py` (`default_password = hash_password("password123")`), `seed_demo_full.py`, `tests/conftest.py`, `scripts/e2e.sh` and `scripts/demo_accounts.py`.
**Reproduction (of the recurrence, not of a current failure):** recreate the development volume (`docker compose -p sycumain-v2 down -v && up`) so `SEED_DEMO_DATA` re-seeds, then click any demo chip. The chip fills `Sycumain2026!`; the freshly seeded accounts hold `password123`; login returns `401` and the form reappears with no visible cause — the identical symptom already reported twice.
**Root cause:** the credential is restated in the seeder, the fixtures, the harness and the login page instead of being defined once. The earlier fix corrected the *literal*, not the *duplication*.
**Why it is not fixed here:** the correct fix touches the seeder, ~20 test modules, the e2e harness and the rotation script; that is a broad change, not the "clearly identified, low-risk" correction this assessment is permitted to make, and it would break dozens of tests that legitimately log in with the catalogue default on their own disposable stacks.
**Affected users/modules:** demo operator; every presenter; any future environment that seeds fresh.

### R-2 — Rotation script cannot re-authenticate after rotation — **P2**

**Severity:** P2. **Evidence [V]:** `scripts/demo_accounts.py` defaults `--admin-password` to `password123`, but the admin account was rotated to `Sycumain2026!` and, per the script's own purpose, no seeded account retains `password123`. Re-running the documented command without the flag therefore fails to authenticate.
**Correction:** read the admin credential from `.demo-credentials.json` when present, or make the flag required with a clear message. Same root as R-1.

### R-3 — Full WebKit end-to-end suite is uncertified — **P2**

**Severity:** P2 (certification coverage, not a live fault).
**Evidence [C]:** full suite `E2E_BROWSERS=chromium,webkit ./scripts/e2e.sh` → 83 passed, 23 failed, 6 did not run. The 23 are the console-hygiene assertion counting WebKit-blocked Next.js RSC **prefetches**; the pages' own assertions had already passed. The narrower 27-test certification subset (11 accessibility + 16 smoke) **passes 27/27 on WebKit 26.6** after the tracker was taught to ignore cancellations.
**Reading the two reports together:** they are not contradictory, they describe different suites — but neither document cross-references the other, which reads as a contradiction (see R-7). For a Chromium-based presentation this is not blocking; for a Safari-only audience it is an open item.

### R-4 — Firefox cannot launch on this host — **P2**

**Severity:** P2, environment. **Evidence [C]:** every test fails in ~1 ms with `Failed to launch … Could not find profile folder`, reproduced outside Playwright against a fresh profile and a second cached build, on macOS 27.2.1. Not an application defect; the browser matrix claim must be made on a supported host.

### R-5 — Demo affordance in a shipping route — **P2**

**Severity:** P2. The chips and `DEMO_PASSWORD` live in the login **page**, gated by `process.env.NODE_ENV !== "production"` **[V]**. `NODE_ENV` is statically replaced by Next, so the branch is eliminated in a production build — but I did not inspect the emitted bundle to confirm the constant is dropped **[N]**. Recommend verifying it once against a production build artifact, and moving the credential to an env var in the same change as R-1.

### R-6 — Single API worker and a 3.8 GiB container budget — **P2**

**Severity:** P2 (operational). Phase 7 measured one uvicorn process saturating at ~10 concurrent users (p95 4.3 s at 50) while four workers sustained ~80 rps at p95 1.6 s [C]. Separately, the host's Docker VM is 3.824 GiB shared with V1's stack, and the Next dev compiler has twice been OOM-killed mid-compile; `restart: unless-stopped` and route pre-warm mask it, but a kill looks like a slow page. Both are configuration, not code.

### R-7 — Documentation drift — **P3**

Four stale statements in documents the brief names as authoritative:

| Document | Statement | Current truth |
|---|---|---|
| `engineering-assessment-v3-2026-11-24.md` | "`next build` fails outright"; "`tsc --noEmit` fails"; "`alembic check` fails"; "browser-test harness is gone" | All four **fixed** **[V]**: tsc exit 0, `alembic check` clean, `scripts/e2e.sh` + `docker-compose.test.yml` present, production build certified in the remediation and rehearsal reports [C] |
| `engineering-assessment-v3-2026-11-24.md` | `sycumain-v2-db` on `:5434` is an "orphan/leftover database" | **Actively required**: it is the pytest fixture database. The full suite just ran green against it **[V]**. It must not be deleted. |
| `functional-certification-v3.md`, `engineering-remediation-v3.md` | Session cookie is `session_token` | Now `sycumain_session` **[V]** (live `Set-Cookie` and `auth-stability.spec.ts`) |
| `final-presentation-readiness-v3.md` vs `production-readiness-certification-v3.md` | WebKit "PENDING" vs WebKit "PASS 27/27" | Both true of different suites; neither says so. See R-3. |

**No P0 defect was found.** The reported "login loop" is resolved at its mechanism and verified live.

---

## E. Verification results

### E.1 Executed in this session

| Check | Command (abridged) | Result |
|---|---|---|
| Repository identity | `git rev-parse --show-toplevel/--abbrev-ref/HEAD` | `…/SYCUMAIN_V2`, `main`, `8467300` |
| Working tree | `git status --porcelain=v1 -uall` | 52 modified, 44 untracked, 0 deleted/renamed, 0 stashes, 0 conflict markers |
| Full backend regression | `.venv/bin/python -m pytest -q` | **1,052 passed, 2 skipped, 0 failed** — exit 0, 953 s |
| Targeted backend (change-related) | `pytest tests/test_origin_guard.py test_session_stability.py test_admin_password_reset.py test_email_delivery.py` | **45 passed**, 48.6 s |
| Backend import | `python -c "import app.main"` | OK (one Starlette deprecation warning, pre-existing) |
| Frontend typecheck | `node_modules/.bin/tsc --noEmit` | exit 0 |
| Translation & error-code parity | `node scripts/check-i18n.mjs` | 2,567 keys × 5 locales; 145 dynamic keys resolve; 216 codes have messages; **pass** |
| Model ↔ migration agreement | `docker compose exec api alembic check` | **"No new upgrade operations detected."** |
| Migration state | `alembic current` / `heads` | both `c4d7e91b2f68 (head)` |
| Schema spot-check (read-only) | `psql` information_schema / pg_indexes / alembic_version | column nullable `timestamptz`; `email_outbox` present; index renamed; revision at head |
| Origin guard, live | `curl -X POST /api/v1/auth/login` with four Origin variants | `evil.example → 403`; `localhost:3101 → 401`; `127.0.0.1:3101 → 401`; no Origin → `401` |
| Production compose | `docker compose --env-file .env.production.example -f docker-compose.prod.yml config -q` | exit 0 (requires a populated env file; fails loudly without one — correct) |
| Service health | `docker compose ps`; `/health`; `/en/login` | api healthy 10,942 s; web up; both `200` |
| Demo sign-in, live | `node scripts/login-debug.mjs http://localhost:3101 student@school.portal` | Authenticated; rendered the student timetable |
| Demo account state (read-only) | `psql` on the four seeded accounts | all `is_active`, `must_change_password=false`, no deadline outstanding |
| V1 isolation | `curl :3100/`, `:8000/health` | `307`, `200` — V1 running and untouched |

### E.2 Not executed — and why

| Check | Status | Reason |
|---|---|---|
| Playwright browser suites (any engine) | **[N]** | No browser-relevant code changed beyond what the suites already certified; running the isolated e2e stack would consume the memory budget the live stack needs. |
| `next build` (production artifact) | **[N]** | Certified on this tree in the remediation/rehearsal phases [C]; `tsc` is green; a build on this host risks OOM-killing the demonstration stack. Recommended once on a non-demo host before release. |
| Production bundle inspection for the demo constant | **[N]** | See R-5. |
| Cross-role object-level authorisation smoke | **[N]** | Unchanged code path; previously certified [C]. |
| Load / soak | **[N]** | Configuration unchanged since the certified measurements; no value in repeating on a demo host. |
| Firefox | **[N]** | Cannot launch on this host (R-4). |

### E.3 Certification status, stated precisely

- **Retested successfully now:** 1,052 backend tests; TypeScript; i18n parity; migration consistency; schema objects; origin guard; demo sign-in; service health.
- **Previously verified, unchanged, not retested:** Chromium 27/27 + WebKit 27/27 certification subset, 24/24 role pages with 0 console errors, edit persistence, 65-minute session soak, backup/restore byte integrity, cold-restart recovery, real-SMTP and real-ClamAV paths, 4-worker capacity.
- **Failed / open:** full WebKit e2e (83/23, prefetch noise), Firefox (environment).
- **Unaffected by this wave (by inventory):** academic period/intake/offering/timetable logic, housing and bed capacity transactions, immigration verification governance, document authorisation and scanning, program-change approval.

---

## F. Recovery priorities

**P0 — blockers: none.** The system is internally consistent and the demonstration path works.

**P1 — resolve before any production conversation:**
1. **R-1** Single source of truth for the demonstration credential (seeder, fixtures, harness, login page, rotation script).
2. **Production decision set** still open and each one blocks: mail provider and From policy; canonical data source; retention plus RPO/RTO and an off-host backup target; trusted public origin list; TLS strategy; whether MANAGEMENT holds `users.manage`.
3. **R-5** Prove the demo affordance and constant are absent from a production build.

**P2 — next development phase:**
4. **R-6** Run ≥4 API workers behind the proxy; add an uptime check on `/ready` and a 5xx alert; raise the container memory budget or isolate the demo stack.
5. **R-3** One clean isolated full WebKit run with the prefetch classifier applied, then record the result in both documents.
6. **R-2** Make the rotation script self-sufficient.
7. Report-only CSP, then a policy.

**P3 — defer:** documentation reconciliation (R-7); removal of the `HTTP_422_UNPROCESSABLE_ENTITY` deprecation; pinning production images by digest from CI.

---

## G. Recommended next development phase

**Phase 8 — Credential Single-Source and Release Hardening.** Deliberately narrow: no domain features, no refactoring, no redesign.

**Objective.** Remove the last order-dependent behaviour in the demonstration path and close the release-configuration gaps, so that "it works" is a property of the code rather than of the current database contents.

**Dependencies.** This assessment (complete); development stack healthy; no schema change required.

**Affected modules.** `apps/api/app/seed.py`, `seed_demo_full.py`, `tests/conftest.py` and fixtures, `scripts/demo_accounts.py`, `scripts/e2e.sh`, `apps/web/e2e/accounts.ts`, `apps/web/src/app/[locale]/login/page.tsx`, `docker-compose.yml`, `.env.production.example`.

**Required implementation.**
1. Introduce one authoritative demo credential (env-driven, defaulted in development only) consumed by the login page; make `demo_accounts.py --show` the human readback; align the seeder and fixtures to the same value; leave the e2e stack free to keep its own catalogue default.
2. Rotation script reads the admin credential from `.demo-credentials.json` when the flag is absent.
3. Verify once against a production build artifact that no demo affordance or credential is emitted.
4. Apply the worker count and the `/ready` uptime check in `docker-compose.prod.yml`.

**Verification criteria.** A fresh `down -v` + `up` + chip click signs in as all four roles; the documented rotation command succeeds twice in a row; `pytest` stays at 1,052 passed / 2 skipped; `check-i18n`, `tsc`, `alembic check` stay green; the production bundle contains no `DEMO_PASSWORD` or chip markup; the API answers `/ready` and survives a killed worker.

**Completion conditions.** R-1, R-2 and R-5 closed with the above evidence; R-6 configured and measured once; no new uncommitted change outside the listed files.

---

## H. Go / no-go

| Decision | Verdict | Basis |
|---|---|---|
| **Safe for continued development** | **GO** | Tree coherent, 0 conflicts, suite green on current code, migrations consistent, stack healthy, no P0. |
| **Safe for internal demonstration** | **GO** | Live sign-in verified this session; 24/24 pages, edit persistence and soak previously certified; restart policy and route pre-warm in place. Keep the demonstration stack alone on the host (R-6) and use `Sycumain2026!`. |
| **Ready for institutional UAT** | **GO to begin — conditional** | Fit to be taken into UAT, but UAT itself has not happened; conditions are the §F P1 institutional decisions and a Firefox run on a supported host. Do not report UAT as passed. |
| **Technically production-ready** | **NO-GO** | Mail provider, origins/TLS, retention/RPO, multi-worker, monitoring/alerting, off-host backup and CSP are unresolved. |
| **Ready for real institutional data migration** | **NO-GO** | No approved source extract and none of the four target cohorts exist in any available database; the V1 anomalies in the Phase 7 §10 inventory must be resolved by the institution first. |

---

## Appendix — reproduce this assessment

```bash
cd SYCUMAIN_V2
git rev-parse --abbrev-ref HEAD && git rev-parse HEAD
git status --porcelain=v1 -uall
docker compose ps && curl -s localhost:8001/health
docker compose exec -T api alembic current && docker compose exec -T api alembic check
cd apps/api && .venv/bin/python -m pytest -q          # 1,052 passed, 2 skipped
cd ../web && node_modules/.bin/tsc --noEmit && node scripts/check-i18n.mjs
node scripts/login-debug.mjs http://localhost:3101 student@school.portal
```

**Boundaries honoured:** V1 untouched; no database reset, merge or destructive migration; no seed run; no write endpoint exercised beyond a normal sign-in; no commit, push or deploy; no product code modified by this assessment.
