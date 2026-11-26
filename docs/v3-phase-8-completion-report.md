# V3 Phase 8 — Completion Report

**Scope:** close the gaps recorded in `docs/v3-change-impact-and-recovery-assessment.md`,
establish a reproducible baseline, and hand over a prioritised development roadmap.
**Date:** 2026-11-25 · **Branch:** `main` · **HEAD:** `8467300` (nothing committed, nothing pushed)

---

## 1. Summary

Every gap the Phase 7 assessment left open has been closed, and the one real defect
it documented — a demonstration credential defined in two places — is now a single
value that seeding, the login page, the rotation script and the development compose
file all derive from, with a regression test that fails if they ever drift.

The verification that matters is that the defect is fixed **at its root**: a database
created from empty now produces four accounts that sign in with the documented
credential, `password123` is rejected, a restart changes nothing, and the real
development database was fingerprinted before and after and is unchanged.

No application behaviour was weakened to achieve this, no test was skipped, and no
schema change was made.

| Gate | Result |
|---|---|
| Backend suite (full, after the change) | **1,059 passed, 2 skipped** — exit 0 |
| TypeScript (`tsc --noEmit`) | exit 0 |
| Localization | 2,567 keys × 5 locales, 145 dynamic keys, 216 error codes |
| Migration consistency | `c4d7e91b2f68`, `alembic check` → no new operations |
| Production build (`next build`) | success, 144/144 static pages, standalone output |
| Production container image | built, served, inspected — no credentials |
| Browser authentication certification | **10/10** scenarios, Chromium |
| 60-minute authenticated soak | **57 cycles, 0 session failures** |

---

## 2. Fixed and verified

### 2.1 Demonstration credentials are one value in one place (Part B)

**Before:** the login page's account chips filled `Sycumain2026!` (one hard-coded
string); the seeder wrote `password123`; `seed_demo_full.py` had its own
`DEMO_PASSWORD = "password123"`; `scripts/demo_accounts.py` defaulted its
`--admin-password` to `password123`, which no longer authenticated. Recreating the
development volume therefore produced accounts the documented chips could not sign
in to — the "login is broken" symptom, reproducible on demand.

**Now:**

- `Settings.DEMO_PASSWORD` is the single definition (`Sycumain2026!` by default).
- `seed_test_users(db, *, password=...)` is seeded from it by the application
  (`main.py`); the **test fixture keeps its own `password123`**, so the pytest suite
  is independent of a value intended for demonstrations.
- `seed_demo_full.py` hashes `settings.DEMO_PASSWORD` for the synthetic cohort —
  no second constant.
- The login page reads `NEXT_PUBLIC_DEMO_PASSWORD`, which `docker-compose.yml` sets
  from the same `DEMO_PASSWORD` variable, with a documented fallback.
- `scripts/demo_accounts.py` resolves the administrator password from
  `DEMO_ADMIN_PASSWORD` → the credentials it recorded last time → `DEMO_PASSWORD`,
  and never from `password123`.
- `docker-compose.test.yml` and `docker-compose.perf.yml` pin their own
  `password123` explicitly, so the disposable stacks cannot inherit a change meant
  for a presentation.
- **New:** `apps/api/tests/test_demo_credentials.py` (7 tests) fails if the API
  default, the login-page fallback, the rotation-script fallback or the compose
  wiring drift apart — and asserts the password is stored as a real hash.

Hashing was not weakened, no institutional administrator credential is hard-coded,
and admin-assisted recovery is untouched.

**Verification (fresh, throwaway database `school_portal_freshdemo` on `:5434`,
separate API on `:8003`; the development database was never reset):**

```
migrations from empty : a7c1e9b25d40 → b8d2f4a61c93 → c4d7e91b2f68 (head)
admin@        login=200 me=200 must_change_password=False
management@   login=200 me=200 must_change_password=False
teacher@      login=200 me=200 must_change_password=False
student@      login=200 me=200 must_change_password=False
logout=200  re-login=200  me-after-re-login=200
old catalogue credential password123 = 401
restart: users 29 → 29 (idempotent), admin login after restart = 200
development DB fingerprint: identical before and after (UNCHANGED=yes)
```

The throwaway database was dropped afterwards.

### 2.2 Demo credentials are absent from production artifacts (R-5, previously unchecked)

Verified against three separate artifacts, not inferred:

| Artifact | Result |
|---|---|
| `.next/static`, `.next/server`, `.next/standalone` | no occurrence of the demo password |
| Standalone server on `:3003`, `/en/login` | 200, 157,148 bytes, form present, **0** password hits, **0** demo-email hits |
| Docker image `sycumain-v3-web:phase8` (310 MB) | no `.env*`, no source, no password; served page identical; `/ar/login` has `dir="rtl"` |

The only remaining trace in the served HTML is the inert `demoNotice` translation
string inside the serialized next-intl catalogue — a message key, not markup and not
a credential. The chip panel and its account list are compiled out by the
`NODE_ENV !== "production"` gate.

### 2.3 Focused browser authentication certification (Part C)

New spec `apps/web/e2e/phase8-auth-certification.spec.ts`, **10/10 passing** in the
final full run (1.5 min):

| # | Scenario | Result |
|---|---|---|
| 1 | Fresh login, dashboard init, initial components, `/auth/me` 200 | pass |
| 2 | Navigation across 7 protected modules, each rendering its own heading | pass |
| 3 | Refresh + second tab + returning to the first tab share one cookie | pass |
| 4 | Transport failure is not an expiry; retry recovers without signing in | pass |
| 5 | A single 401 from a background request does not end a valid session | pass |
| 6 | 403 is an authorization answer, not a logout | pass |
| 7 | Dead session → one redirect to login, with an explanation | pass |
| 8 | Explicit sign-out invalidates the cookie server-side; re-login works | pass |
| 9 | All five locales keep the session; Arabic is RTL, others LTR | pass |
| 10 | Role route access enforced by the server, not the menu | pass |

Scenario 8 replays the pre-logout cookie through an API request context (a browser
`fetch` cannot set a `Cookie` header, which would have made the check vacuous).

**Two corrections were to the spec, not the product.** The account menu is portalled
and re-rendered by the notification poll, which can steal focus between a keypress
and the menu opening; the certification drives it with the pointer (the keyboard path
remains certified by `smoke.spec.ts`). And the `Accounts`/`Audit log` entries collapse
into the "More" popover at this width, so role access is asserted by route behaviour
and `href`, not by a visible label.

### 2.4 Sustained session (60 minutes)

```
status            : passed_with_transport_aborts
duration          : 60 min        cycles: 57
account           : admin@school.portal
session failures  : 0
transport aborts  : 2  (ERR_EMPTY_RESPONSE on /app/academics and /app/students)
second tab        : shared the session (True)
/auth/me          : 200 on every cycle that completed
```

Both aborts are Next **dev-server** responses that returned no body while a
production build and the full test suite were running on the same 3.8 GiB Docker
budget. They are classified separately from session outcomes precisely so host
contention cannot masquerade as an authentication defect: no cycle ended on the login
page, and no cycle lost an identity it already had.

### 2.5 Release baseline (Part F)

`docs/v3-release-baseline.md` — source state, ports, startup commands, environment
variables, migration head, credential model, health checks, exact test commands with
measured results, known limitations, and a restore procedure that does not destroy
data.

---

## 3. Previously verified and unchanged

Re-verified only where this phase's change could reach; otherwise carried forward
with the reason it is unaffected.

| Item | Status |
|---|---|
| 1,052 backend tests | **Re-run in full** (shared startup seeding changed): 1,059 passed / 2 skipped, exit 0 — the 7 new tests account for the difference |
| Origin guard / CSRF | Covered by `test_origin_guard.py` in that suite; live checks unchanged |
| Session stability, admin reset, email delivery | Covered in the same run |
| TypeScript | Re-run: clean |
| Localization | Re-run: pass (no message files changed) |
| Alembic model↔database | Re-run in the api container: head, no new operations |
| Demo login and timetable | Re-verified live: `student@school.portal` signs in, timetable renders |
| V1 (`/Users/ezra/SYCUMAIN`, `:3100`/`:8000`/`:5433`) | Untouched throughout; read-only checks only |

Nothing in Parts B–D changed a route, a permission, a migration or a translation, so
the historical browser, load and migration-rehearsal evidence remains valid for the
code it certified.

---

## 4. Not tested (and why)

| Area | Status | Reason |
|---|---|---|
| Firefox | **Cannot run** | The browser cannot launch on this host ("Could not find profile folder", macOS 27.2.1) — environment, not application |
| Full WebKit suite | Not run | Historically 83 passed / 23 failed / 6 blocked by RSC prefetch classification; the narrow 27-test authentication subset is the certified WebKit evidence |
| Production-shaped stack (Caddy, HTTPS, prod compose **up**) | Not run | Only `docker compose -f docker-compose.prod.yml config` validation; bringing it up needs a domain/certificate and would compete with the demo stack for memory |
| Real institutional data migration | Not run | Explicitly out of scope; needs a data copy, retention decisions and a rollback rehearsal |
| Backup / restore rehearsal | Not run | Scripts exist (`scripts/backup.sh`, `restore.sh`, SHA-256 manifest); not exercised this phase |
| Email over a real SMTP relay | Not run | No relay configured; `test_email_delivery.py` uses a double |
| Load / performance re-run | Not run | No route, query or index changed; historical load results remain valid |

---

## 5. Known limitations

1. **Host contention.** Docker Desktop is capped at 3.824 GiB shared with V1. The Next
   dev compiler has been OOM-killed before; the two soak aborts above are the same
   cause. Do not run a build, the full suite and a browser soak simultaneously.
2. **The host virtualenv's alembic target is not the V3 database.** From the host,
   `alembic current` reports `a7c1e9b25d40` while the api container reports
   `c4d7e91b2f68 (head)`; the settings fallback is `localhost:5433`, which belongs to
   V1. Migrate through `docker compose exec api python -m alembic …` only.
3. **The Playwright teardown writes to its target database.** It marks `STU-E2E-*`
   students `INACTIVE` and ends their housing assignment. The synthetic cohort
   (`STU-001`…`STU-125`) is not matched, but prefer `./scripts/e2e.sh` unless the
   browser checks are deliberately aimed at the live development build.
4. **No `clamav` service in the production composition.** `CLAMAV_HOST` points at a
   service that is not defined there and `MALWARE_SCANNER` defaults to `disabled`, so
   uploads fail closed until an external scanner endpoint is supplied.
5. **Development builds show the demo chips.** That is intended for the demo stack;
   institutional UAT should use a production build, where they do not exist.

---

## 6. Remaining blockers (honest list)

None of these block development or an internal presentation. All of them block a
production deployment with real data:

1. **Real-data migration rehearsal** against a copy of institutional data, with a
   verified rollback. The workflows for identity conflicts exist
   (`IDENTITY_MISMATCH`, `AMBIGUOUS_IDENTITY`), but they have not been run on real
   data.
2. **Retention policy values** — `RETENTION_*` is unset on purpose; the retention
   report answers "policy pending approval". An institution must supply these.
3. **Malware scanning endpoint** for document upload in production (see 5.4).
4. **Production-shaped rehearsal** — Caddy, HTTPS, real origins in `CORS_ORIGINS`,
   secure session cookie, and the production image behind them, exercised end to end.
5. **Email delivery**, only if the institution wants notification mail or self-service
   reset. Admin-assisted recovery does not depend on it.

---

## 7. Verdict

| Question | Verdict | Basis |
|---|---|---|
| **Development readiness** | **GO** | Full suite green, types clean, migrations consistent, reproducible credential model, baseline documented |
| **Internal presentation readiness** | **GO** | Chips, seeded password and rotation script now agree; fresh initialisation verified; 24/24 pages, edit persistence and a 60-minute soak behind it |
| **Institutional UAT readiness** | **GO, with conditions** | Sign in, roles, permissions, navigation, all five locales and session behaviour are certified on Chromium. Conditions: use named UAT accounts (not the shared demo password), use a production build (no demo chips), and decide which admission phase gates are enabled |
| **Technical production readiness** | **NO-GO** | Build, image and artifact hygiene pass — but no production-shaped rehearsal, no scanning endpoint, retention unset, no migration dry run. Passing a build is not production readiness |
| **Real-data migration readiness** | **NO-GO** | No rehearsal on a real data copy, no rollback exercise, retention policy undecided |

---

## 8. Next phase

The prioritised roadmap — P0 through P3, grouped into four implementation phases with
the justification and migration impact of each — is
[`docs/v3-next-development-roadmap.md`](v3-next-development-roadmap.md).

Headline: **no application-blocking P0 defects remain.** The P0 items are the four
production-adoption blockers in §6. Development continues with the institutional
workflow and operational items the roadmap groups as Phase 9.

No schema change and no architectural rewrite is proposed in any phase.
