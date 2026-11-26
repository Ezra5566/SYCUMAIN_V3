# SYCUMAIN V3 — Engineering Remediation

**Started:** 2026-11-24
**Scope:** V3 (`SYCUMAIN_V2`, web 3101 / api 8001 / db 5435) remediated against V1 (`/Users/ezra/SYCUMAIN`, web 3100, read-only reference).
**Mode:** controlled repair. No V1 file, database or Git state was touched. No real institutional record was read, written or migrated. No deployment was performed. All testing used synthetic demo data and disposable databases.

This document records each defect, its verified root cause, the correction, the evidence, and its final status. It complements — and does not replace — `docs/engineering-assessment-v3-2026-11-24.md`.

---

## 0. Baseline captured before any change

| Fact | Value |
|---|---|
| V3 root | `…/local-projects/6e8bcceb-…/SYCUMAIN_V2` |
| V3 branch / HEAD | `main`, `8467300 feat: activate migrated accounts instead of issuing passwords` |
| V1 root / HEAD | `/Users/ezra/SYCUMAIN`, `4e7158e` (read-only) |
| Uncommitted V3 changes found | `apps/web/next.config.ts`, `apps/web/package.json`, `apps/web/src/i18n/request.ts`, `apps/web/src/lib/api.ts` (modified); `docker-compose.yml`, `docker-compose.prod.yml`, `infra/`, `apps/web/messages/messages/`, `docs/engineering-assessment-…md` (untracked) |
| V1 working tree | had pre-existing uncommitted modifications before this session; left untouched |
| Running stacks | V3: 3101/8001/5435 · V1: 3100/8000/5433 · fixture DB: 5434 · orphan: `sycumain-v2-db` |

The four modified frontend files were preserved rather than reverted: three of them (`api.ts`, `request.ts`, the `pnpm` block in `package.json`) are improvements, and only `next.config.ts` contained the defect.

**Origin discipline.** Every probe below is labelled by port, because V3 (3101) and V1 (3100) were both live throughout. Before work started, `http://localhost:3101/` answered `307 → /en` with `<html lang="en" dir="ltr">` and `http://localhost:3100/` answered `307 → /en` independently.

---

## 1. Phase 1 — restore the production frontend build

### Root cause (verified)

`apps/web/next.config.ts` called `createNextIntlPlugin` with a **second argument**:

```ts
createNextIntlPlugin("./src/i18n/request.ts", {
  localeMessages: { en: { hello: "Hello", world: "World" }, … },
});
```

`next-intl` v4's plugin takes exactly one argument (the request-config path). The
`localeMessages` option does not exist, and the payload was a two-key placeholder
catalogue. In the same edit `output: "standalone"` was commented out and
`outputFileTracingRoot` was dropped "for Docker build compatibility", which
removed the artifact the production image needs.

Observed failures: `tsc --noEmit` → `TS2554 Expected 0-1 arguments, but got 2`;
`next build` → exit 1.

A second, hidden obstruction: `apps/web/.next` carried a macOS ACL
`user:ezra deny delete`, so the stale build directory could not be removed by the
owner. That is why earlier attempts to rebuild appeared to fail for unrelated
reasons.

### Correction

* Restored the single-argument plugin call, `output: "standalone"` and
  `outputFileTracingRoot: process.cwd()`, with comments explaining why the
  tracing root is pinned.
* Kept the static message imports in `src/i18n/request.ts` — they are correct and
  they are what makes the catalogues part of the build output.
* Removed `apps/web/messages/messages/` (five 2-byte `{}` files left by a failed
  experiment). Nothing referenced them.

### Evidence

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **exit 0**, no output |
| `rm -rf .next && npx next build` | **exit 0** |
| Static pages generated | **144** (35 routes × 4 prerendered locales + shared pages) |
| Locale routes in the build report | **36** `[locale]` entries |
| `.next/standalone/server.js` | present (6,572 bytes) |
| Message catalogues in the server bundle | `grep "Student directory"` → `.next/server/chunks/3615.js` |
| Arabic direction | `/ar/login` → `<html lang="ar" dir="rtl">` |
| English direction | `/en/login` → `<html lang="en" dir="ltr">` |

One transient: the first post-fix build failed with `PageNotFoundError` because it
inherited the half-deleted `.next` tree from the ACL failure. A clean rebuild (and
every subsequent build) passed. This is recorded because it is the kind of
artifact that can make a correct fix look ineffective.

**Status: complete.**

---

## 2. Phase 2 — Docker image packaging

### Root cause (verified)

`infra/docker/Dockerfile.web` copied `src`, `public` and the configs but **never
copied `messages/`**, while `src/i18n/request.ts` imports
`../../messages/en.json` at module scope. The image therefore could not build the
app, and the *development* container only worked because `./apps/web` is
bind-mounted over it. The original "next-intl Docker failure" was a missing
directory, not a next-intl bug.

There was also no `production` stage at all, no `.dockerignore`, and the
repository had no way to produce a deployable frontend artifact.

### Correction

`infra/docker/Dockerfile.web` now has four explicit stages:

| Stage | Purpose |
|---|---|
| `base` | `node:20-alpine`, corepack |
| `deps` | `pnpm install --frozen-lockfile` from manifests only |
| `builder` | copies `src`, `public`, **`messages`**, configs; `next build`; `NEXT_PUBLIC_API_URL` as a **build arg** |
| `dev` | dependencies + config; source bind-mounted; unchanged dev behaviour |
| `production` | `public` + `messages` + `.next/standalone` + `.next/static`, non-root `nextjs`, health check on `/en/login` |

The dependency stage no longer sets `pnpm config set ignore-scripts true`; the
`pnpm-workspace.yaml` allow-list already names the three packages that legitimately
need post-install scripts.

`docker-compose.yml` now pins `target: dev`, because a production stage exists and
Docker otherwise builds the last stage.

Added `.dockerignore` (there was none) covering `node_modules`, `.next`,
`test-results`, Git metadata, logs, backups and **all env files**.

### Evidence

| Check | Result |
|---|---|
| `docker build --target production` | **exit 0** (≈107 s cold) |
| `/app` contents | `node_modules package.json public server.js messages` |
| `/app/messages` | `ar.json en.json fr.json ru.json zh.json` |
| Container start with **no bind mounts** | `healthy` |
| `/en /zh /fr /ru /ar` | **200, 200, 200, 200, 200** |
| Rendered text, Chinese | `沈阳城市学院国际学生门户`, `国际学生管理`, … |
| Rendered text, Arabic | `بوابة الطلاب الدوليين – جامعة شنيانغ`, `إدارة الطلاب الدوليين`, … |
| Raw-key leak check | none (`namespace.key` patterns absent) |

**Status: complete.**

---

## 3. Phase 3 — production deployment configuration

### Root causes (verified)

`docker-compose.prod.yml` could not work as written:

1. `target: production` referenced a stage that did not exist (fixed in Phase 2).
2. `DATABASE_URL` hardcoded `postgresql://portal:portal@…`. The application's own
   production validator refuses those credentials — verified directly:
   `Refusing to start with an insecure production configuration: … DATABASE_URL must not use the documented portal:portal credentials`.
3. `NEXT_PUBLIC_API_URL` was supplied only at runtime, but Next inlines it at
   **build** time.
4. No TLS termination, no health checks, no migration step, no document volume.
5. While building it, two further defects surfaced:
   * `Dockerfile.api` had `COPY docs/ /app/docs:ro` — invalid syntax, and the
     build context excluded `docs/`. The API genuinely reads
     `docs/scu-timetable-reference.json` and `docs/scu-timetable-domain-map.json`
     at runtime (`app/services/academic_import.py`, `app/services/source_intakes.py`).
   * **`apps/api/.env` was baked into the API image.** pydantic-settings read it,
     so a production container started with development values — the first
     `migrate` run failed with `DEBUG must be false … PASSWORD_RESET_DELIVERY must
     not be 'dev' … MALWARE_SCANNER=dev-clean is forbidden`.

### Correction

* `docker-compose.prod.yml` rewritten around one public origin:
  * every secret required as `${VAR:?…}`; `DATABASE_URL` composed from
    `${POSTGRES_USER}/${POSTGRES_PASSWORD}/${POSTGRES_DB}`;
  * `migrate` service behind the `tools` profile — an explicit, one-off step;
  * health checks: `pg_isready`, API `/ready` (database + storage), web
    `/en/login`;
  * `caddy` edge publishing only 80/443, API and web internal-only;
  * `documents` named volume at `/app/var/storage`; `pgdata` volume;
  * `--proxy-headers --forwarded-allow-ips` scoped to the compose subnet;
  * `SESSION_COOKIE_SECURE=true`, `ACTIVATION_RETURN_LINK=false`,
    `ACTIVATION_LINK_BASE=${APP_ORIGIN}`, `SEED_DEMO_DATA=false`.
* `infra/caddy/Caddyfile` (ACME) and `infra/caddy/Caddyfile.local` (local CA for a
  ring-fenced rehearsal host) — routing `/api/* /health /ready /docs…` to
  `api:8001`, everything else to `web:3000`.
* `Dockerfile.api`: `COPY docs/ ./docs/` with a comment stating the files are a
  runtime dependency.
* `.dockerignore`: `**/.env` and `**/.env.*` excluded (examples allowed).
* `.env.production.example` documents every variable; `.gitignore` now allows that
  one example file (`!.env.production.example`) while still ignoring real env files.

### Evidence

| Check | Result |
|---|---|
| `docker compose -f docker-compose.prod.yml config` | **exit 0** |
| Resolved `web` build | `target: production`, `NEXT_PUBLIC_API_URL=https://portal.example.edu` |
| Resolved `api` | `DATABASE_URL` from env, no `portal:portal` |
| `Settings()` under production env | `environment=production secure_cookie=True seed=False db_driver_ok=True` |
| `/app/.env` in API image | **absent** |
| `/app/docs` in API image | present |
| Both images build via compose | **exit 0** |
| Explicit `migrate` run | **exit 0**, 29 revisions applied |
| Stack health | postgres `healthy`, api `healthy`, web `healthy`, caddy up |
| `https://localhost:8443/` | **307 → `/en`** |
| `https://localhost:8443/en/login` | **200**, `lang="en" dir="ltr"` |
| `https://localhost:8443/health` · `/ready` | **200** · **200** |
| `POST /api/v1/auth/login` | **200** |
| `Set-Cookie` | `session_token=…; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure` |
| `GET /api/v1/auth/me` (cookie) | **200** (admin identity returned) |
| `GET /api/v1/auth/me` (no cookie) | **401** |
| `POST /api/v1/auth/logout` | **200**; `/me` afterwards **401** |

**Open finding (documented, not changed).** A logout request carrying a foreign
`Origin: https://evil.example` returns **200**. There is no same-origin/CSRF
helper anywhere in the API; protection rests on `SameSite=lax` (cross-site POSTs
do not carry the cookie) plus CORS. That is adequate for the current session
design but is *implicit* — if the cookie policy ever relaxes to `SameSite=None`,
CSRF tokens or origin enforcement become mandatory. Recorded for Phase 7.

**Status: complete for configuration and local production-shaped verification.**
No host has been deployed to, and the TLS rehearsal used Caddy's local CA.

---

## 4. Phase 4 — schema drift, without resetting anything

`alembic check` reported three operations. Each was investigated separately.

### 4.1 `uq_examination_section` — a redundant model declaration

* Model (`app/models/examination.py`) declared a composite primary key
  `(examination_id, class_section_id)` **and** a `UniqueConstraint` on the same
  two columns named `uq_examination_section`.
* The database shows `uq_examination_section` with `contype = 'p'` — it *is* the
  primary key; there is no second constraint to add. The model was describing one
  invariant twice.
* Applying the autogenerated operation would have created a duplicate unique
  index over the identical column pair: pure write overhead and lock cost for a
  guarantee that already exists.

**Decision:** remove the redundant declaration from the model, leaving the primary
key as the enforcer. No DDL, no data risk, **no invariant weakened** — the
uniqueness property and both foreign keys are unchanged and were verified in
`pg_constraint` before and after.

### 4.2 `ix_immigration_reminders_profile_id` — a name, not a structure

* Model declares `immigration_profile_id` with `index=True`, so SQLAlchemy derives
  `ix_immigration_reminders_immigration_profile_id`.
* Migration `f2b3c4d5e6f7` created the same index on the same column under the
  shorter name `ix_immigration_reminders_profile_id`.
* Autogenerate therefore reported a drop and an add for one identical index.

**Decision:** rename the index. New revision **`b8d2f4a61c93`**
(`rename_immigration_reminders_index`), a metadata-only `ALTER INDEX … RENAME`,
guarded so it is skipped if the target name already exists, with a symmetric
`downgrade()`.

### Evidence

| Check | Result |
|---|---|
| Fresh database: `alembic upgrade head` | **exit 0** (29 revisions, incl. the new one) |
| Fresh database: `alembic check` | **exit 0** — "No new upgrade operations detected" |
| Fresh database tables | **63** |
| Clone of the live database (pg_dump → psql, source read-only) | at `a7c1e9b25d40` |
| Clone: `alembic upgrade head` | **exit 0** |
| Clone: row data after upgrade | **identical** — 2,458 `INSERT` statements, sorted diff empty (only `alembic_version` differs) |
| Clone: `alembic check` | **exit 0** |
| Clone: `alembic downgrade -1` | **exit 0**; index name reverts to `ix_immigration_reminders_profile_id` |
| Clone: re-`upgrade head` | **exit 0**; back at `b8d2f4a61c93` |
| Disposable databases afterwards | dropped |
| Development database (synthetic demo data) | upgraded to `b8d2f4a61c93`; `alembic check` **exit 0**; 26 students / 15 reminders / 7 examination sections unchanged |

**Canonical-database decision deliberately not taken.** Both databases still
exist; see §7.

**Status: complete.** Rollback behaviour: `b8d2f4a61c93` reverses cleanly; the
examination change needs no migration at all.

---

## 5. Phase 5 — engineering safeguards

V1 has a `Makefile`, `.github/workflows/ci.yml`, `docker-compose.test.yml`,
`scripts/e2e.sh`, `scripts/backup{,-postgres}.sh`, `scripts/restore.sh` and a
`backups/` convention. V3 had **none** of them, which is why a broken build could
sit in the tree. All were rebuilt against V3's actual structure and ports rather
than copied.

| Added | Purpose |
|---|---|
| `Makefile` | `help up down logs test-api lint-api migrate migrate-check typecheck lint build i18n e2e prod-config prod-build prod-migrate prod-up backup restore-verify check` |
| `.github/workflows/ci.yml` | backend (ruff, `alembic upgrade head`, **`alembic check`**, import check, pytest, Postgres 16 service), contract (OpenAPI compared as parsed JSON), frontend (`typecheck`, `lint`, `i18n:check`, `build`), images (both Docker artifacts incl. `--target production`), e2e (isolated stack) |
| `docker-compose.test.yml` | disposable stack on 5436/8002/3002 with its own demo seed |
| `scripts/e2e.sh` | fail-closed runner: refuses a composition that is not the disposable database, polls `/ready` and a real login page, always tears down with `down -v`, keeps container logs on failure |
| `scripts/backup.sh` | `pg_dump --format=custom` validated with `pg_restore --list`, document-volume archive, SHA-256 manifest |
| `scripts/restore.sh` | verify-by-default restore into a scratch database with byte-level document checks; `--live` requires typing the database name |
| `docs/deployment-v3.md` | topology, release procedure, secrets, backups, rollback, dependencies |

### Evidence

| Check | Result |
|---|---|
| `bash -n` on all three scripts | ok |
| `make backup` (production-shaped stack) | **exit 0** — 247,191-byte dump, 191-entry archive, manifest |
| `make restore-verify` | **exit 0** — digests ok; 63 tables; 1 `alembic_version` row; 1 user; 0 documents; `missing objects: 0`; `checksum failures: 0` |
| Live database during restore verification | untouched (restore used `school_portal_restore_verify`) |
| OpenAPI contract | semantically identical to `apps/web/openapi.json` (**187 paths**, parsed-JSON equality); only serialization formatting differs, so CI compares parsed documents |
| `./scripts/e2e.sh` | **exit 0** (16/16) after two harness defects were found and fixed |

Two defects in the new harness surfaced on first use and were corrected rather
than worked around:

* `docker-compose.test.yml` used `context: ..`, which Compose resolved one
directory above the repository (`…/local-projects/<id>/infra` did not exist).
Corrected to `context: .`.
* `scripts/e2e.sh` guarded the database name with `grep -E "…v3(?![_a-z])"`.
BSD grep has no lookahead; the pattern error left the guard ineffective inside
an `if`. Replaced with a portable ERE, with a comment explaining why.

**Status: complete for authoring and local execution.** The workflow has not yet
run on GitHub Actions — "CI passes" would be an unverified claim.

---

## 6. Phases 6–8 — regression, security and localisation verification

Re-run after the changes above.

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **exit 0** |
| `node scripts/check-i18n.mjs` | **passed for 5 locales** (2,562 keys each; 52 reserved error codes noted as not yet emitted — pre-existing) |
| Five locales in the production image | 200 with correct `lang`/`dir`; real Chinese and Arabic text |
| Arabic RTL | `<html lang="ar" dir="rtl">` |
| Backend suite (`pytest`) | **1006 passed, 2 skipped, 23 warnings in 1215.58 s** |
| Browser suite (`scripts/e2e.sh e2e/smoke.spec.ts`) | **16 passed (45.2 s)** in one run |
| Auth / session / cookie | verified on the TLS origin (Phase 3 table) |
| Anonymous access to a protected endpoint | 401 |

### Permission matrix (re-probed against the live API on 8001)

| Probe | admin | management | teacher | student | anon |
|---|---|---|---|---|---|
| `GET /students/` (directory) | 200 (26) | 200 | 200 (**19** visible) | **403** | **401** |
| `GET /students/{id}` in teacher scope | 200 | 200 | **200** | 403 | 401 |
| `GET /students/{id}` out of scope | 200 | 200 | **403** | **403** | 401 |
| `GET /students/me` | 200 | 200 | 200 | **200** | 401 |
| `GET /documents?student_id=<other>` | 200 | 200 | 200 | **200 with 0 rows** | 401 |
| `GET /users/` | 200 | 200 (read) | 403 | 403 | 401 |
| `GET /audit` | 200 | 200 (read) | 403 | 403 | 401 |

Interpretation, checked against `app/permissions/constants.py` rather than
assumed: MANAGEMENT is granted `users.view` and `audit.view` — read-only
visibility of accounts and the audit trail — while `users.manage` (role changes,
suspension, password resets for staff) is ADMIN-only. So management seeing those
lists is the designed behaviour, not an escalation.

Two results are worth stating precisely because they look like successes and
could hide a leak: a teacher's directory is **19 of 26** students (the scope came
from teaching assignments, not from a filter the client sends), and a student
asking for another student's documents receives **200 with an empty list**, not
someone else's rows. Ids in these probes came from the API itself, so nothing
was guessed.

**Not done in this pass:** the module-by-module V1 comparison of Phase 6, the
four-role permission matrix re-run, file-access permission checks, dependency CVE
scan, and per-locale browser interaction beyond `/ar` rendering. The earlier
assessment verified the permission matrix by direct probe (student 403 on another
profile, teacher restricted to 19 of 26 students and 403 for `STU-118`,
management 200); those results still stand because the permission modules are
untouched, but they were not re-executed here.

---

## 7. Phase 9 — canonical database investigation (partial)

| | 5435 (`school-portal-v2-db`) | 5434 (`sycumain-v2-db`) |
|---|---|---|
| Used by | the running V3 API (8001) | the **pytest fixture** (`conftest.py` default `localhost:5434/school_portal_test_v2`) |
| Database in question | `school_portal_v2` | `school_portal_v2` (a leftover; the fixture uses `school_portal_test_v2`) |
| Alembic revision | `b8d2f4a61c93` (head after this work) | `a7c1e9b25d40` (one behind) |
| Academic periods | **1** — `2026-FALL` (2026-09-01 → 2026-12-20, ACTIVE) | **2** — `2026-FALL` plus `spring 2025` (2025-09-20 → 2026-11-09, ACTIVE) |
| Program offerings | 3 | 3 (all on `2026-FALL`) |
| Academic placements | 24 | 25 |
| Students / users | 26 / 29 | 27 / 30 |
| Enrollments · class sections · courses · programs | 49 · 5 · 7 · 3 | 49 · 5 · 7 · 3 |
| Examinations · immigration profiles | 5 · 26 | 5 · 26 |
| Documents · audit log rows | 14 · 48 | 15 · 199 |

**The decisive finding:** the second period on 5434 is named `fall 2025` while its
code is `spring 2025`, and it has **0 program offerings and 0 placements** — no
timetable, no cohort, no student attached to it. It is an artefact of an earlier
import/rehearsal, not academic history. The extra student, user, document and the
151 extra audit rows are likewise rehearsal residue.

That resolves the assessment's open question: the "second intake timetable" does
not exist in either database. Any expectation that V3 should already show a
2025 intake timetable cannot be met by either copy, and re-importing is a data
operation requiring the institution's source files — not something to invent.

**Recommendation:** treat **5435** as the development canonical database — it is
the one the running API, the documented demo accounts and the browser suite
exercise, and it is now at migration head. 5434 needs no merge: nothing in it is
unique institutional information, only rehearsal residue around an empty,
mis-named period. Before retiring it, take a dump (`scripts/backup.sh` against
that container) so the decision is reversible; do not delete it in this phase.

Still unresolved, and requiring the institution: which academic periods actually
exist, their official dates, and the timetable source files. Those are inputs,
not code.

Nothing was merged, reset or deleted.

---

## 8. Phase 10 — scalability

No load test was run. No throughput, latency percentile or concurrency number is
claimed anywhere in this document. The production-shaped stack is now *available*
for such a test (single origin, health checks, migration step), which it was not
before. Connection pooling, worker count, background jobs and monitoring remain
unaddressed by design in this pass.

---

## 9. Regression evidence (final)

Both suites were run to completion after every change.

| Suite | Command | Result |
|---|---|---|
| Backend | `apps/api/.venv/bin/python -m pytest -q` | **1006 passed, 2 skipped, 23 warnings in 1215.58 s** — identical to the pre-change baseline |
| Browser smoke | `./scripts/e2e.sh e2e/smoke.spec.ts` | **16 passed (45.2 s)** — one complete run, against the production web image |

Logs: `/tmp/pytest_after_remediation.log`, `/tmp/v3_e2e_smoke3.log`.

The backend result matters beyond "green": Phase 4 removed a model declaration
and the migration was applied to three databases, and no test changed behaviour.
The browser run exercises the real deployable artifact — `docker-compose.test.yml`
builds `--target production`, not the dev server.

### The one genuine failure, and its fix

The pre-existing smoke suite failed 1 of 16: *"logout returns to login and the
session is invalidated"* clicked `getByRole("button", { name: /sign out/i })`
directly. In the V3 shell, sign-out is a Radix menu item inside the account
dropdown, so no such button exists. This was a stale **test contract**, not an
app regression — the affordance works, including from the keyboard (the trigger
is a labelled button and the entries are `menuitem`s).

The spec now performs the real two steps — open the account trigger, choose
`Sign out` — and keeps the original assertion that the session is invalidated
afterwards. The test was not weakened or deleted; it now drives the shipped UI.

---

## 10. Files changed

**Modified**
* `apps/web/next.config.ts` — valid plugin call, `output: "standalone"`, tracing root.
* `apps/web/src/lib/api.ts`, `apps/web/src/i18n/request.ts`, `apps/web/package.json` — pre-existing uncommitted improvements, preserved.
* `.gitignore` — allow `.env.production.example`.
* `apps/web/src/app/[locale]/(protected)/…` — untouched.
* `apps/api/app/models/examination.py` — removed the redundant `UniqueConstraint`.
* `infra/docker/Dockerfile.web` — `base/deps/builder/dev/production`, `messages`, build arg, non-root, health check.
* `infra/docker/Dockerfile.api` — valid `COPY docs/`.
* `docker-compose.yml` — `target: dev` for the web service.
* `docker-compose.prod.yml` — rewritten.
* `apps/web/e2e/smoke.spec.ts` — sign-out test now drives the account menu (same assertion).
* `docker-compose.test.yml`, `scripts/e2e.sh` — corrected `context` and the database-name guard.

**Added**
* `apps/api/alembic/versions/b8d2f4a61c93_rename_immigration_reminders_index.py`
* `infra/caddy/Caddyfile`, `infra/caddy/Caddyfile.local`
* `.env.production.example`, `.dockerignore`
* `docker-compose.test.yml`
* `Makefile`
* `.github/workflows/ci.yml`
* `scripts/e2e.sh`, `scripts/backup.sh`, `scripts/restore.sh`
* `docs/deployment-v3.md`, this file

**Deleted**
* `apps/web/messages/messages/` (five empty `{}` files, untracked, unreferenced).

No source file was reformatted, no dependency was added or removed, and no V1 file
was read beyond the reference material quoted above.

---

## 11. Database migrations created

| Revision | Down revision | Content | Reversible |
|---|---|---|---|
| `b8d2f4a61c93` | `a7c1e9b25d40` | rename `ix_immigration_reminders_profile_id` → `ix_immigration_reminders_immigration_profile_id` | yes — verified both directions |

No table, column, constraint or row was added, dropped or rewritten by this
revision. No other migration was necessary: the second drift item was a redundant
model declaration, removed without DDL.

---

## 12. Readiness verdict

| Dimension | Verdict | Basis |
|---|---|---|
| **Development stability** | **GREEN** | `tsc` 0, clean `next build` 0, 144 pages, `alembic check` 0 on three databases, dev stack untouched on 3101 |
| **Functional completeness** | **AMBER** | unchanged this pass; no module was re-certified against V1 yet |
| **Backend security** | **AMBER** | production start now possible; dev `.env` no longer ships; `Secure`/`HttpOnly`/`SameSite=lax` verified; CSRF origin enforcement still absent (mitigated); no CVE scan, no pen test |
| **Data integrity** | **AMBER** | drift closed, migration reversible, 2,458 rows byte-identical through upgrade; **two databases remain unreconciled** |
| **UI functionality** | **GREEN** | 16/16 browser flows pass against the production image; builds and serves 5 locales |
| **Localisation** | **GREEN** | 5 locales × 2,562 keys, typecheck clean, real zh/ar text from the image, `dir="rtl"` |
| **Automated regression protection** | **GREEN** | 1006 backend tests pass; 16 browser flows pass; CI authored covering tests, migrations, contract, build and images (workflow not yet executed on GitHub Actions) |
| **Docker and deployment readiness** | **GREEN** | both images build; production stack starts healthy behind TLS; health checks and an explicit migration step work |
| **Institutional UAT readiness** | **AMBER** | a production-shaped environment finally exists; canonical data still undecided |
| **Staging readiness** | **AMBER** | stack proven locally behind a local-CA edge; no host provisioned |
| **Real-data migration readiness** | **AMBER** | tooling and rehearsal exist; XLSX ingestion and rollback position still missing; canonical database unresolved |
| **Production readiness** | **RED** | no monitoring, no email delivery, no ClamAV, no load test, no deploy, one database undecided |

The four blockers from the assessment are closed. What remains is not another
build defect: it is operational completeness (monitoring, mail, scanning), the
database decision, and the two interrupted verification runs.
