# V3 Release Baseline — reproducible state after Phase 8

**Purpose.** Describe the actual source tree and runtime that exist on this machine
today, so the next development phase starts from a known state instead of
rediscovering it. Nothing here assumes a clean repository: the working tree is
deliberately uncommitted and is part of the baseline.

- **Baseline date:** 2026-11-25
- **Repository:** `SYCUMAIN_V2` (the V3 clone)
- **Branch:** `main`
- **HEAD:** `8467300` — *feat: activate migrated accounts instead of issuing passwords*
  (2026-11-24 08:05:45 +0800)
- **V1 reference installation:** `/Users/ezra/SYCUMAIN` — **read-only, untouched.**

---

## 1. Source state

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `8467300fcb09efa3ea1d5735df1b6e2c6c2b0473` |
| Modified files | **54** |
| Untracked files | **47** (counted with `git status -uall`; 34 with directory collapsing) |
| Deleted / renamed files | **0** |
| Stashes | **0** |
| Commits made in Phase 8 | **none** (no commit, no push — as instructed) |

The working tree carries the whole of the V3 remediation work: V1→V3 migration
changes, the Phase 1–7 feature work, plus the Phase 8 corrections listed below.
**Do not `git checkout`, `git clean`, `git reset` or rebase this tree.** Every file
here is either finishing work or evidence.

### 1.1 Files changed in Phase 8

The demo-credential correction (Part B) touched these files:

| File | Change |
|---|---|
| `apps/api/app/config/settings.py` | New `DEMO_PASSWORD` setting with the drift warning documented in place |
| `apps/api/app/seed.py` | `seed_test_users(db, *, password=...)`; the default stays the **test fixture** credential |
| `apps/api/app/seed_demo_full.py` | Cohort users hash `settings.DEMO_PASSWORD` instead of a module constant |
| `apps/api/app/main.py` | Startup passes `settings.DEMO_PASSWORD` when demonstration seeding runs |
| `apps/web/src/app/[locale]/login/page.tsx` | Chips read `NEXT_PUBLIC_DEMO_PASSWORD`, falling back to the same default |
| `scripts/demo_accounts.py` | `--admin-password` no longer defaults to the retired `password123` |
| `docker-compose.yml` | One `DEMO_PASSWORD` variable feeds both the API seed and the web build |
| `docker-compose.test.yml`, `docker-compose.perf.yml` | Pin their own `password123` so the disposable stacks stay independent |
| `.env.example` | Documents `DEMO_PASSWORD` |
| `apps/api/tests/test_demo_credentials.py` | **New** — drift guard (7 tests) |
| `apps/web/e2e/phase8-auth-certification.spec.ts` | **New** — focused browser certification (10 tests) |

---

## 2. Runtime topology

| Service | Container | Port | Health |
|---|---|---|---|
| V3 web (Next 15.5.29) | `school-portal-v2-web` | **3101** → 3000 | `GET /en/login` → 200 |
| V3 API (FastAPI) | `school-portal-v2-api` | **8001** | `GET /health` → 200, `GET /ready` |
| V3 database (PostgreSQL 16) | `school-portal-v2-db` | **5435** → 5432 | `pg_isready` |
| V1 web | `school-portal-web` | 3100 | 307 (untouched) |
| V1 API | `school-portal-api` | 8000 | 200 (untouched) |
| V1 database | `school-portal-db` | 5433 | untouched |
| Pytest fixture database | `sycumain-v2-db` | **5434** | required by the backend suite; **do not delete** |

Compose project: `sycumain-v2`. Database `school_portal_v2`, user/password
`portal`/`portal`. The **service name for `psql` is `postgres`, not `db`**.

```bash
# Verify before touching anything
for p in 3100 8000 5433 3101 8001 5435 5434; do printf "%-6s %s\n" "$p" \
  "$(lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1 && echo listening || echo free)"; done
docker ps --format '{{.Names}}\t{{.Status}}'
```

---

## 3. Starting the development stack

```bash
cd SYCUMAIN_V2
./scripts/demo-up.sh          # docker compose up -d --build, waits for readiness,
                              # pre-compiles every demonstration route, then rotates
                              # the four presentation accounts
```

`demo-up.sh` is the supported entry point. It preserves existing data, waits on
real readiness (`/ready`, `/en/login`) rather than sleeping, and pre-warms the
routes so the first click in a presentation does not wait for a Next compile.

Underlying command, if you need it directly:

```bash
docker compose up -d --build     # api runs `alembic upgrade head` on start
./scripts/demo-down.sh           # stop, keep volumes
```

**Never use `down -v` on the development stack**: it deletes the demonstration
database volume. That is only correct for the disposable e2e stack, which
`scripts/e2e.sh` owns.

### 3.1 Required environment variables (development)

| Variable | Development value | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://portal:portal@postgres:5432/school_portal_v2` | In compose; `+psycopg` is added automatically |
| `ENVIRONMENT` | `development` | Production refuses demo seeding |
| `SECRET_KEY` | dev-only string | Production requires ≥32 unique characters |
| `CORS_ORIGINS` | `["http://localhost:3101","http://127.0.0.1:3101"]` | Also authorises writes (origin guard) |
| `SEED_DEMO_DATA` | `true` | Unset means "on unless production" |
| `DEMO_PASSWORD` | `Sycumain2026!` | Seed password **and** the value the login chips fill |
| `NEXT_PUBLIC_DEMO_PASSWORD` | same value | Set by compose from `DEMO_PASSWORD` |
| `PASSWORD_RESET_DELIVERY` | `dev` | Production allows `disabled` or `smtp` only |
| `MALWARE_SCANNER` | `dev-clean` | Production requires `clamav` |
| `SESSION_COOKIE_NAME` | `sycumain_session` | Namespaced vs V1's cookie |

`apps/api/.env` exists on this machine and influences host-side tooling — see
§7.2 before running anything from the host virtualenv.

---

## 4. Database

- **Migration head:** `c4d7e91b2f68` (*Phase 7: temporary credential deadlines and the email outbox*)
- **`alembic current`** (in the api container): `c4d7e91b2f68`
- **`alembic check`**: *No new upgrade operations detected.*

```bash
# The correct place to inspect or migrate the V3 database
docker exec school-portal-v2-api sh -c \
  "python -m alembic current && python -m alembic heads && python -m alembic check"
```

Migrations are additive: Phase 7 added `users.temporary_password_expires_at`
(nullable) and the `email_outbox` table, and Phase 6 renamed an index to match
the model. No data was rewritten.

Demo data volume: 28 students in the development database (STU-001 plus the
25-student synthetic cohort, of which 23 are `ACTIVE`), 14 active housing
assignments, one graduating and one withdrawn record held for the reports.

---

## 5. Accounts and the demonstration credential

### 5.1 One source of truth

`DEMO_PASSWORD` (API setting) → development seeding **and** the login page's
account chips (`NEXT_PUBLIC_DEMO_PASSWORD`, set from the same compose variable).

- Default: **`Sycumain2026!`** (13 characters, all four character classes).
- `apps/api/tests/test_demo_credentials.py` fails if the API default, the login
  page fallback, the rotation-script fallback, or the compose wiring drift apart.
- A production build compiles the chips out entirely; the string is **absent**
  from every served artifact (verified — see §6.3).

### 5.2 The four synthetic accounts

| Role | Email | Purpose |
|---|---|---|
| ADMIN | `admin@school.portal` | Institutional administration, accounts, audit |
| MANAGEMENT | `management@school.portal` | Read + approvals |
| TEACHER | `teacher@school.portal` | Scoped to own class sections |
| STUDENT | `student@school.portal` | Self-service, `STU-001` |

### 5.3 Two supported credential paths

1. **Fresh initialisation** (empty volume, `SEED_DEMO_DATA=true`): all four
   accounts and the 25-student cohort receive `DEMO_PASSWORD`. Predictable, and
   the login chips therefore work immediately.
2. **Rotation for a presentation** (`python3 scripts/demo_accounts.py`): issues a
   fresh random 18-character password to each account through the admin-assisted
   reset endpoint (the same counter process the international office uses),
   verifies each one can sign in and is not behind the forced-change screen, and
   records the result in `.demo-credentials.json` (mode 0600, git-ignored).

```bash
python3 scripts/demo_accounts.py           # rotate + verify
python3 scripts/demo_accounts.py --show    # print the stored credentials
```

The script now signs in as the administrator using `DEMO_ADMIN_PASSWORD`, then
the credentials it recorded last time, then `DEMO_PASSWORD` — never the retired
`password123`. It prints which source it used, never the value.

### 5.4 Verification performed (fresh, throwaway database)

A dedicated database `school_portal_freshdemo` was created on the fixture
container, migrated from zero, and served by a separate API process on `:8003`.
The development database was fingerprinted before and after.

- Migrations from empty: `a7c1e9b25d40 → b8d2f4a61c93 → c4d7e91b2f68 (head)`.
- All four accounts: `login=200`, `/auth/me=200`, `must_change_password=False`.
- Logout → re-login → `/auth/me`: `200 / 200 / 200`.
- Old catalogue credential `password123`: **401**.
- Restart against the same database: 29 users before and after (idempotent),
  administrator login still 200.
- Development database fingerprint (`count(users)` and an MD5 over
  `email||hashed_password`): **identical** before and after.
- The throwaway database was dropped; the development database was never reset.

### 5.5 Password policy unchanged

Admin-assisted recovery is still the process: an administrator issues a
time-limited temporary password (`TEMPORARY_PASSWORD_EXPIRE_HOURS=72`) that is
single-use in effect, because the account is blocked from every screen except the
change-password screen until it is replaced. Self-service email recovery remains
an optional channel that requires an institutional SMTP relay.

---

## 6. Verification commands and results

### 6.1 Backend

```bash
cd apps/api && .venv/bin/python -m pytest -q
```

- Historical baseline (unchanged code paths): **1,052 passed, 2 skipped** (953 s).
- **Full suite re-run after the Phase 8 change, because startup seeding is shared
  behaviour: 1,059 passed, 2 skipped (1,035 s), exit 0** — the seven new drift-guard
  tests account for the difference.
- Phase 8 drift guard: `tests/test_demo_credentials.py` → **7 passed**.
- Targeted authentication suites (`test_origin_guard`, `test_session_stability`,
  `test_admin_password_reset`, `test_email_delivery`): **45 passed**.

The suite creates and drops every table in `school_portal_test_v2` on `:5434`,
and refuses to run against any URL that is not loopback + `school_portal_test*`.

### 6.2 Frontend

```bash
cd apps/web && npx tsc --noEmit            # exit 0
node scripts/check-i18n.mjs               # 2,567 keys × 5 locales, 145 dynamic keys, 216 error codes
NEXT_PUBLIC_API_URL="" npx next build     # success, 144 static pages, standalone output
```

Build facts: compiled in 5.2 s, 144/144 static pages generated, shared JS 103 kB,
middleware 46.3 kB, all five locales prerendered for every static route
(36 HTML files under `.next/server/app`, 7 of them Arabic).

### 6.3 Production artifact checks

- `.next/static`, `.next/server`, `.next/standalone`: **no occurrence** of the
  demo password. (The only hits are in `.next/cache/webpack/*.pack`, which are
  build-cache blobs and are excluded from every image by `.dockerignore`.)
- The standalone server was started on `:3003` and `/en/login` fetched:
  `200`, 157,148 bytes, sign-in form present, CSS/JS present, **0** occurrences
  of `Sycumain2026`, **0** of `admin@school.portal` / `student@school.portal`.
  The only trace of the demo panel is the inert `demoNotice` translation string
  inside the serialized next-intl catalogue.
- `/ar/login` served with `dir="rtl"`.
- No `.env`, `SECRET_KEY` or `POSTGRES_PASSWORD` content in the standalone tree.

### 6.4 Browser authentication certification (Chromium)

```bash
cd apps/web
E2E_BASE_URL=http://localhost:3101 E2E_API_URL=http://localhost:8001 \
E2E_PASSWORD='<demo password>' \
npx playwright test e2e/phase8-auth-certification.spec.ts --project=chromium
```

Ten scenarios: fresh login and component rendering, navigation across seven
protected modules, refresh and multi-tab, transport failure, a single 401 from a
background request, a 403, a dead session, explicit sign-out and re-login, all
five locales with Arabic RTL, and role-specific route access.

**Result: 10 passed (1.5 min).** Run them alone: running the suite while a soak or a
build is also using the host produced a false failure in an early attempt
("Checking authentication…" timed out under contention), which is a host-resource
artifact, not an application defect.

### 6.5 Sustained session (soak)

```bash
cd apps/web && SOAK_PASSWORD='<demo password>' SOAK_EMAIL=admin@school.portal \
  node scripts/session-soak.mjs 60 http://localhost:3101
```

**Result: 60 minutes, 57 cycles, 0 session failures, 2 transport aborts
(`ERR_EMPTY_RESPONSE` while a build and the full suite were running), second tab
shared the session, `/auth/me` 200 on every completed cycle.** The script writes
`.perf/session-soak.json` and `.perf/session-soak.log`, and classifies transport
aborts separately so host contention cannot be reported as a logout.

---

## 7. Known limitations and traps

### 7.1 Host resources

Docker Desktop is limited to 3.824 GiB shared with the V1 stack. The Next **dev**
compiler has been OOM-killed on this host before; `restart: unless-stopped` plus
`scripts/demo-up.sh` pre-warming masks it. Do not run the Playwright suite and a
long soak at the same time as a build — that is host contention, not an
application defect (it produced one `ERR_EMPTY_RESPONSE` in the soak, correctly
classified as transport).

### 7.2 The host virtualenv's alembic target is NOT the V3 database

`apps/api/.env` exists on this machine and points the host-side default
`DATABASE_URL` somewhere other than the V3 development database: from the host,
`alembic current` reports `a7c1e9b25d40`, while the api container reports
`c4d7e91b2f68 (head)`. A bare `alembic upgrade head` from the host virtualenv
would therefore migrate the wrong database — and the fallback default in
`settings.py` is `localhost:5433`, which is the **V1** PostgreSQL server.

**Always migrate through the compose service:**

```bash
docker compose exec api python -m alembic upgrade head
docker compose exec api python -m alembic current
```

Recommended follow-up (not done here): a fail-closed guard in `alembic/env.py`,
mirroring the one `tests/conftest.py` already has, that refuses any database
whose name is not `school_portal_v2`/`school_portal_test*`.

### 7.3 Browser coverage

- **Firefox cannot launch on this host** ("Could not find profile folder",
  macOS 27.2.1) — an environment limitation, not an application defect.
- WebKit is certified only for the narrow 27-test authentication subset. The full
  WebKit run reports 83 passed / 23 failed / 6 not run because the harness counts
  blocked RSC prefetches as failures.
- The focused Phase 8 certification runs on **Chromium only**.

### 7.4 The Playwright teardown mutates the target database

`e2e/global-teardown.ts` marks every `STU-E2E-*` student `INACTIVE` and ends their
housing assignment. It therefore writes to whichever database `E2E_API_URL`
names — including the development stack. The synthetic demonstration cohort
(`STU-001`…`STU-125`) is not matched and is not affected, but prefer
`./scripts/e2e.sh` (its own disposable stack) unless you specifically want the
browser checks against the live development build.

### 7.5 Test credentials are deliberately separate

The pytest suite and the disposable e2e/perf stacks sign in with `password123`,
pinned in `tests/conftest.py`, `docker-compose.test.yml` and
`docker-compose.perf.yml`. That is intentional: changing the demonstration
credential must not silently change what the suite tests.

---

## 8. Restoring the environment without damaging data

```bash
cd SYCUMAIN_V2

# 1. Normal restart — data preserved
./scripts/demo-down.sh && ./scripts/demo-up.sh

# 2. Credentials no longer match the login chips
python3 scripts/demo_accounts.py                 # re-rotate and verify
#    or reset to the seeded value:
#    docker compose exec -T postgres psql -U portal -d school_portal_v2 \
#      -c "..."   # only with an explicit, reviewed statement

# 3. Take a backup before anything risky
./scripts/backup.sh                              # -> backups/
./scripts/restore.sh <file>                      # documented restore path

# 4. If a worker died
docker compose ps
docker compose restart api web
docker compose logs --tail 100 api web
```

**Do not** delete the `sycumain-v2` volumes, the `sycumain-v2-db` container, or
the `school_portal_v2` database to "fix" a problem. Every seeded table is
idempotent and re-running the seed adds nothing.

---

## 9. Exact re-verification set

The smallest set that proves this baseline still holds:

```bash
# Backend: credential model + authentication contract
cd apps/api && .venv/bin/python -m pytest -q \
  tests/test_demo_credentials.py tests/test_auth.py \
  tests/test_session_stability.py tests/test_admin_password_reset.py \
  tests/test_origin_guard.py

# Frontend: types, translations, build
cd apps/web && npx tsc --noEmit && node scripts/check-i18n.mjs && \
  NEXT_PUBLIC_API_URL="" npx next build

# Runtime: health + one real sign-in
curl -fsS http://localhost:8001/health >/dev/null && echo api-ok
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:3101/en/login

# Browser: focused authentication certification
E2E_BASE_URL=http://localhost:3101 E2E_API_URL=http://localhost:8001 \
E2E_PASSWORD='<demo password>' npx playwright test \
  e2e/phase8-auth-certification.spec.ts --project=chromium
```

The full 1,052-test suite is the historical baseline; re-run it only when shared
authentication, middleware, seeding or database behaviour changes.
