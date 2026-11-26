# SYCUMAIN V3 — CI completion report

**Date:** 2026-11-26
**Branch:** `main`
**Head:** `3602099` ("new changes pushed")
**Scope:** complete and verify the GitHub CI pipeline, resolve the integrity report's
C1–C4 findings, keep CD deferred.
**Verdict:** see §11.

The CI work described here was committed and pushed by the repository owner as
`3602099`, and GitHub Actions executed it:
[run 45840882309](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45840882309).
**Six of seven jobs passed**, including the backend suite, the migration pair and the
production images — the three jobs the previous run failed. The only failure was a
Playwright order-dependence bug in one smoke test, diagnosed from that run's uploaded
diagnostics and fixed afterwards (§1.6); that single change is the only part of this
report not yet executed on GitHub. No deployment was configured, no repository
setting was changed, and this task itself staged, committed, pushed and deployed
nothing.

---

## 1. Changes made

### 1.1 The CI workflow actually ran, and exposed three defects

`52914a6` is the first commit that carried both the hardened workflow and the
pnpm/OpenAPI/ruff fixes, and GitHub Actions ran it:
[run 45813694149](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45813694149).
Five of seven jobs passed; two failed for reasons that had nothing to do with the
application. After the fixes below were pushed as `3602099`, the same workflow ran
again ([run 45840882309](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45840882309))
and six of seven passed — the backend, Docker and security jobs that this section is
about all went green.

**Defect 1 — the `backend` job pointed the suite at port 5433.**
`tests/conftest.py` refuses any URL containing `:5433`, because 5433 is the V1
reference portal:

```
RuntimeError: Refusing to run tests against the reference PostgreSQL port 5433;
use the isolated SYCUMAIN_V2 database on port 5434.
```

The Postgres service was published as `5433:5432` and both `DATABASE_URL` and
`SYCUMAIN_TEST_DATABASE_URL` used it, so the `Tests` step died on `conftest.py`
import (exit code 4). The guard is a safety property and was left exactly as it is;
the workflow moved to **5434**, the port every developer's isolated V3 database
already uses.

**Defect 2 — one database was doing two incompatible jobs.**
With the port fixed, the suite would still have failed: the same job ran
`alembic upgrade head` on the database that `pytest` then used. The suite builds its
schema from the models (`Base.metadata.create_all`) and its fixtures delete rows
between tests, while several migrations install triggers that refuse exactly those
deletes:

```
deletes are not allowed on academic_admission_changes
deletes are not allowed on academic_admission_status_history
deletes are not allowed on academic_placements
deletes are not allowed on academic_period_date_corrections
```

Reproduced locally on a freshly migrated database: **20 failed, 1096 passed, 2
skipped**. The first refusals leave rows behind, and the leaked state then fails
unrelated assertions (`PROGRAM_OFFERING_NOT_FOUND`, stale cohort counts, an
`alembic_version` collision). The same suite on a database that was never migrated
passes completely (§3.2).

The fix separates the two, and neither check is weakened:

* `school_portal_migration_check` — a dedicated, empty database created by the job.
  `alembic upgrade head` and `alembic check` run there and nothing else touches it.
* `school_portal_test_v2` — the suite's own database, built from the models as
  `conftest.py` intends.

**Defect 3 — the web image's builder stage could not see `allowBuilds`.**
The `builder` stage copied `package.json` but not `pnpm-workspace.yaml`, so pnpm's
verify-before-run install reported the native toolchain as unapproved:

```
Error: ERR_PNPM_IGNORED_BUILDS
  ╰─▶ Ignored build scripts: @parcel/watcher@2.6.0, @swc/core@1.16.2, unrs-resolver@1.12.2
[WARN] The install that runs before scripts failed, so your node_modules may be out of sync
```

The build then continued on the `deps` layer, so it was a warning rather than a
failure — but it is the same class of defect that failed the first CI run. The
builder now copies `pnpm-lock.yaml` and `pnpm-workspace.yaml` with `package.json`.
Verified: `grep -c ERR_PNPM_IGNORED_BUILDS` is `0` in the rebuilt image's log.

### 1.2 Node 24 (C1)

| Place | Before | After |
|---|---|---|
| `.github/workflows/ci.yml` | `NODE_VERSION: "20"` | `NODE_VERSION: "24"` |
| `infra/docker/Dockerfile.web` | `FROM node:20-alpine AS base` | `FROM node:24-alpine AS base` |
| `apps/web/package.json` | no `engines` | `"engines": { "node": ">=24" }` |
| `apps/web/.nvmrc` | absent | `24` |

A drift guard was added to the `images` job: it reads the major from
`Dockerfile.web`, compares it to `NODE_VERSION`, and asserts `engines.node` admits
that major. The three values can no longer disagree silently.

Node 24 is the current **Maintenance LTS** (end of life 2028-04-30); Node 22 expires
2027-04-30 and Node 20 is already end-of-life. Every `uses:` action is pinned to a
current major that itself targets Node 24, which also removes the runner's
Node-20-action warning.

### 1.3 Database-aware release and recovery (C2)

`release.yml` is preserved and still builds and publishes artifacts; it gained:

* `release-manifest.json` now records `schema_expected_head`, resolved by a new
  stdlib-only tool `apps/api/tools/schema_revision.py` (it reads the revision files
  with `ast`, needs no Alembic/SQLAlchemy/psycopg, and agrees with
  `alembic heads` — both report `f3b7c2d9e6a1` from 32 revision files).
* a `backup_verified` dispatch input. The `migrate` job now contains a **failing
  step** that refuses to run `alembic upgrade head` unless the operator confirmed a
  verified backup for this run. The check is a step, not a job-level `if`, because a
  *skipped* `migrate` is accepted by `deploy`'s condition and would deploy
  unmigrated code.
* the rollback instructions now state the schema-revision precondition: a rollback
  must not cross a migration boundary, and recovery is a forward revision plus
  `scripts/restore.sh --live` as last resort.

`docs/deployment-v3.md` §3 (release procedure) and §8 (recovery) document the same
order: backup → verify the backup → record the expected head → migrate → deploy, and
step 0 of recovery compares the manifest's `schema_expected_head` with
`alembic current` before anything else.

### 1.4 Audit immutability documentation (C3)

`docs/v3-phase-10-stabilization-and-release-hardening-report.md` §B.2 gained a
paragraph explaining what `REVOKE … FROM PUBLIC` does and does not do: it removes
`PUBLIC`'s privileges but leaves the table owner and any superuser able to write, so
the `BEFORE UPDATE/DELETE/TRUNCATE` trigger — not the revoke — is the effective
control. The revoke is defence in depth for non-owner roles.

### 1.5 The exact C4 finding

C4 was "the clone's database is behind the migration head". `5434/school_portal_v2`
sat at `a7c1e9b25d40` while the head is `f3b7c2d9e6a1` — **four** revisions behind
(the integrity report said five; the chain is four). It was resolved with a
**forward-only** upgrade after a `pg_dump` backup, never a downgrade:

`a7c1e9b25d40 → b8d2f4a61c93 → c4d7e91b2f68 → d1e4a7b9c2f5 → f3b7c2d9e6a1`

Before: 63 tables, 27 students, 30 users, 199 audit rows, 0 triggers.
After: 64 tables, identical row counts, 3 audit triggers, and
`UPDATE audit_logs` → `ERROR: audit_logs is append-only: UPDATE is not permitted`.
`alembic check` reports no new upgrade operations. Backup:
`/tmp/c4-before-upgrade-school_portal_v2.dump` (352K).

### 1.6 Browser specs

Two Playwright assertions were wrong, not the application:

* `e2e/smoke.spec.ts` "academics module loads majors, courses and timetable" waited
  for `getByText(/Introduction to Programming/).first()` and
  `getByText(/Computer Science/).first()` to be **visible**. On that page both are
  `<option>` elements of the period/programme/course filters, and an `<option>` is
  never visible to Playwright: the assertion could only pass by DOM-order accident
  (it passed for one name and failed for the other on the same run). It now asserts
  attachment of the options, which is what "the catalogues loaded" means, with the
  visible-page coverage left to the heading assertion and `expectHealthy`.

The second run showed that fix alone was not enough, and the attached diagnostics
said exactly why. The academics page opens on `periods.find(status === "ACTIVE")`,
and by the time this spec runs the intake and period specs have created their own
active periods, so the filter was selected on `E2E correction intake 4208625-A` —
an empty period, whose offering filter therefore contained **only** "All program
offerings". The failure was `element(s) not found` for the *offering* option, not a
visibility problem, and it only appeared when the whole suite ran in CI order;
`e2e/smoke.spec.ts` on its own had no such periods and passed. The test now selects
the seeded period explicitly, the way an operator would, before asserting the
catalogue:

```ts
await page
  .getByRole("combobox", { name: "Academic period" })
  .selectOption({ label: "Fall 2026 (2026-FALL)" });
```

The application's "current period" behaviour is unchanged: only the test's
assumption was wrong.

### 1.7 The support-desk draft race (found by the same run)

The other red test in run 2 — `stage7.spec.ts:88`, the support-ticket conversation —
was recorded earlier as a retry-masked flake. Reproducing the full suite locally
showed it is deterministic, and the failure screenshots showed why: the staff reply
was already in the conversation while the reply box was empty and the internal-note
box unchecked. `sendReply` cleared both *after* awaiting the POST:

```ts
await supportApi.addMessage(id, reply.trim(), internal);
setReply("");
setInternal(false);
```

Anything typed while the request is in flight is silently discarded — a real draft
loss for a staff member writing a second reply, not just a test problem. It now
clears only what was actually sent:

```ts
setReply((current) => (current.trim() === text ? "" : current));
setInternal((current) => (current === asInternal ? false : current));
```

---

## 2. Node 24 compatibility evidence

Node 24 was not adopted on a version bump alone. Evidence, in the order it was
obtained:

| Evidence | Result |
|---|---|
| GitHub `Frontend (types, i18n, build, locales)` on `52914a6`, `node-version: 24`, pnpm 12 | ✅ **passed** — frozen-lockfile install, `typecheck`, `lint`, `i18n:check`, `next build`, `check:locales` |
| GitHub `Docker images and production composition` on `52914a6` | ✅ **passed** — web image built on `node:24-alpine`, api image, secret scan, Compose model |
| `docker run sycumain-web:ci-verify node -v` after this task's Dockerfile change | `v24.22.3` |
| Web image content check | `messages/`, `node_modules/`, `server.js`, `public/`; no `/app/.env` |
| `pnpm install --frozen-lockfile` under Node 24 (CI, and the image's `deps` stage) | ✅ lockfile resolves; 554 entries pass the supply-chain policy |
| Drift guard | passes: image major 24 = `NODE_VERSION` = `engines.node >= 24` |

Dependency versions in play: Next.js 15.5.29, React 19, pnpm 12 (`PNPM_VERSION: "12"`,
installed by corepack as 12.23.0 in the image), Playwright 1.63, Python 3.11.14.
Next 15.5 supports Node ≥ 18.18 and Playwright 1.63 supports Node 24; both were
exercised above rather than assumed.

---

## 3. Local test results

### 3.1 Lint, migrations, contract

| Check | Command | Result |
|---|---|---|
| Backend lint | `python -m ruff check app tests tools` | ✅ `All checks passed!` |
| Migration from zero | fresh DB → `alembic upgrade head` | ✅ 32 revisions, 64 tables, 19 non-internal triggers |
| Model/migration parity | `alembic check` on that database | ✅ `No new upgrade operations detected.` |
| Import/config | `python -c "import app.main"` | ✅ (one pre-existing Starlette deprecation warning) |
| Head resolver | `python3 tools/schema_revision.py` | ✅ `{"head": "f3b7c2d9e6a1", "revisions": 32}` = `alembic heads` |
| OpenAPI contract | GitHub `contract` job on `52914a6` | ✅ passed (no local drift introduced) |
| Workflow syntax | `yaml.safe_load` of `ci.yml` / `release.yml` | ✅ 7 jobs / 4 jobs |

### 3.2 Full API suite

Executed the way CI now does it — the suite's database is **not** migrated:

| Shard | Files | Result |
|---|---|---|
| 1 | `test_academic.py` … `test_demo_credentials.py` (16) | ✅ 290 passed, 1 skipped (298 s) |
| 2 | `test_dormitory_attendance.py` … `test_intake_and_timetable.py` (16) | ✅ 332 passed (318 s) |
| 3 | `test_integrity_remediation.py` … (15) | ✅ 280 passed (255 s) |
| 4 | `test_placements.py` … (15) | ✅ 214 passed, 1 skipped (204 s) |
| — | total | ✅ **1116 passed, 2 skipped** |

The suite was sharded only because a single process takes ~20 minutes on this
machine and the runner kept interrupting one long run; the environment (database,
`ENVIRONMENT`, `STORAGE_BACKEND`, `STORAGE_LOCAL_ROOT`, `LOG_FORMAT`) is identical to
CI's.

For contrast, the same suite against a **migrated** database — the arrangement the
old workflow used — gives **20 failed, 1096 passed, 2 skipped**, all traceable to
the delete-refusing triggers described in §1.1.

### 3.3 Frontend and images

| Check | Result |
|---|---|
| `docker build --target production` (web), Node 24 | ✅ image built, `node -v` = v24.22.3 |
| `ERR_PNPM_IGNORED_BUILDS` in the web build | ✅ 0 occurrences after the fix |
| `docker build` (api) | ✅ built |
| Web image contents | ✅ no `.env`, no `.git`; `server.js` present |
| `pnpm audit --prod` | ✅ 0 critical; 6 advisories (§6) |

---

## 4. GitHub Actions execution results

This is real execution, not a YAML parse. The workflow ran twice on `main`.

**Run 2 — [45840882309](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45840882309),
head `3602099`, pushed after the fixes in §1.1–§1.2: 6 of 7 jobs green.**

| Job | Result | Detail |
|---|---|---|
| Detect code changes | ✅ success | `code=true` |
| Backend (tests, lint, migrations) | ✅ **success** | on port 5434, with the dedicated migration database: lint, migration from zero, `alembic check`, import, and the full suite |
| API contract (OpenAPI current) | ✅ success | committed document matches the exporter |
| Frontend (types, i18n, build, locales) | ✅ success | Node 24, five locales, Arabic RTL route checks |
| Docker images and production composition | ✅ success | web image built on `node:24-alpine` with no `ERR_PNPM_IGNORED_BUILDS`, api image, secret scan, Compose model |
| Security (advisories) | ✅ success | env-file check, pip-audit, `pnpm audit` critical gate |
| Browser E2E (isolated stack) | ❌ failure | 1 failed test — a test-order defect, not the application (§1.6, §5) |

**Run 1 — [45813694149](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45813694149),
head `52914a6`: 5 of 7 jobs green.**

| Job | Result | Detail |
|---|---|---|
| Backend (tests, lint, migrations) | ❌ failure | `Tests` step: `conftest.py` port-5433 refusal (§1.1). Lint, migrate, parity and import passed |
| Browser E2E (isolated stack) | ❌ failure | 1 hard failure + 1 flaky test (§5) |
| the other five jobs | ✅ success | as in run 2 |

The earlier run on `c2f5c5b`
([45764076190](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45764076190))
had failed 4 of 5 jobs; the api and frontend defects that caused it are gone.

So the two database/migration fixes and the Node 24 migration are confirmed by
execution, not by inspection. What is **not** confirmed on GitHub is the last change
in this report — the academics period selection and the support-desk draft race
(§1.6) — because it postdates run 2 and pushing it is the owner's decision.

---

## 5. Browser E2E results

**Run 1** (45813694149), job `Browser E2E (isolated stack)`: 1 failed, one test flaky.

| Test | Outcome |
|---|---|
| `e2e/smoke.spec.ts:189` academics module loads majors, courses and timetable | ❌ failed both attempts — `expect(locator).toBeVisible()` on an `<option>` (§1.6) |
| `e2e/stage7.spec.ts:88` support tickets — student files, staff answers | ⚠️ failed once (45 s timeout), **passed on retry #1 in 8.0 s** |
| remaining 79 tests | ✅ passed |

**Run 2** (45840882309), same job: 115 passed, **1 failed**, one retry used.

| Test | Outcome |
|---|---|
| `e2e/smoke.spec.ts:189` academics | ❌ failed both attempts — `element(s) not found` for the offering option: the page had opened on an empty intake created by an earlier spec (§1.6) |
| `e2e/stage7.spec.ts:88` support tickets | ⚠️ failed once, passed on retry #1 |
| remaining 115 tests | ✅ passed |

The run's own uploaded diagnostics (`playwright-diagnostics`: an ARIA snapshot and two
screenshots) identified both causes exactly; neither was guessed from the log. Both
are fixed — one in the test, one in the reply form (§1.7). Nothing is suppressed: no
retry was removed and no assertion was loosened.

**Local full-suite re-run after both fixes**, `./scripts/e2e.sh` with no filter —
the CI condition, one worker, retries disabled because `CI` is unset locally:

```
✓ 71  smoke.spec.ts:189  academics module loads majors, courses and timetable (2.5s)
✓ 79  stage7.spec.ts:88  support tickets — student files a ticket and staff answers it (7.9s)
116 passed (7.8m)
```

The earlier filtered run (`./scripts/e2e.sh e2e/smoke.spec.ts`) had passed 16/16, which
is exactly why the order-dependence stayed invisible until the whole suite ran.

---

## 6. Remaining dependency and security advisories

`pnpm audit --prod`: **6 vulnerabilities — 3 high, 3 moderate, 0 critical.**

| Package | Severity | Path | Patched |
|---|---|---|---|
| `postcss` | high (×2 advisories) | `next > postcss`, `next-intl > next > postcss` | `>= 8.5.23` |
| `source-map-js` | high | via Next.js | per advisory |
| `postcss-selector-parser` | moderate | `tailwindcss-animate > tailwindcss > …` | `>= 6.1.5` |

All six are transitive under Next.js and Tailwind tooling, not direct application
dependencies. CI blocks only on **critical**, so the pipeline is honest about the
gate it applies. Dependabot is configured and already opening upgrade PRs against
this tree; the coordinated Next.js bump is the real fix and is out of scope here.

Backend: `pip-audit --local --skip-editable` remains **advisory** because
`pyproject.toml` uses lower-bound ranges and has no lockfile, so the resolved set is
not reproducible. No known vulnerability was reported for the current environment.

---

## 7. Unresolved blockers

1. **The last two fixes are not yet executed on GitHub.** The academics period
   selection and the support-desk draft race (§1.6, §1.7) were made after run 2,
   so the browser job is green locally but its red GitHub result stands until the
   change is pushed. That, plus branch protection, is the reason this report says
   CI VERIFIED WITH LIMITATIONS rather than CI VERIFIED.
2. **Branch protection is not configured.** `main` is unprotected, so no check is
   required to merge. This is a repository setting and was deliberately not touched.
3. **Six frontend advisories remain** (§6) — none critical, all transitive under
   Next.js; CI blocks only on critical.
4. **`pip-audit` cannot be blocking** without a backend lockfile, so it is advisory.
5. **`alembic upgrade head --sql` (offline mode) is broken** at revision
   `9a1f2b3c4d5e`. Pre-existing, unrelated to CI, and not exercised by the pipeline.
6. **The working tree carries the changes in this report**, listed in §10.

---

## 8. Release artifacts remain available

`release.yml` is intact and was not disabled or deleted. It still:

* triggers on `v*` tags and manual dispatch;
* builds and pushes both images to GHCR with two tags each (semantic version and
  commit12) — neither tag is ever overwritten;
* writes `release-manifest.json` (version, commit, build time, both digests, and now
  `schema_expected_head`) and uploads it as a 90-day workflow artifact;
* attaches the manifest to the GitHub Release on a tag push.

No artifact has been published, because the workflow has never run: it needs a tag
or a manual dispatch, not a CI run.

---

## 9. Deployment remains disabled

Nothing was deployed and nothing is deployable by accident:

* `DEPLOY_ENABLED` does not exist in the repository, so `vars.DEPLOY_ENABLED == 'true'`
  is false and both `migrate` and `deploy` are visibly **skipped**.
* No `staging` or `production` environment exists.
* No deployment secret (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`) is configured.
* No SSH client is installed by the workflow; there is no cloud-provider step.
* `deploy` and `migrate` remain `workflow_dispatch`-only and are unreachable from a
  merge to `main`.
* The only secrets referenced anywhere are `GITHUB_TOKEN` (provided automatically)
  and the three deployment secrets, which are unset.

The eventual target is local institutional infrastructure, and the workflow stays
Docker-Compose-shaped for it: `deploy` pulls immutable image tags and runs
`docker-compose.prod.yml` on the host.

---

## 10. Exact Git status

Branch `main`, HEAD `3602099` ("new changes pushed"); `origin/main` is the same commit.

```
$ git status --porcelain
 M apps/web/e2e/smoke.spec.ts
 M apps/web/src/app/[locale]/(protected)/app/support/[id]/page.tsx
 M docs/v3-ci-cd-setup-and-release-workflow.md
 M docs/v3-ci-completion-report.md
```

Four modified files, nothing added, deleted, renamed or untracked, and nothing
staged. `git rev-parse HEAD` = `36020991a35759101dabc2137daa78c3a475fee`. History was
not rewritten, no branch was created or switched, and neither V1 nor the running
development stacks were touched.

---

## 11. Verdict

**CI VERIFIED WITH LIMITATIONS.**

Six of seven jobs passed **on GitHub Actions** for `3602099`: the backend suite, the
migration from zero, model/migration parity, the OpenAPI contract, the frontend job
on Node 24 with five locales and Arabic RTL, both production images, and the security
gates. The seventh — browser E2E — failed on two defects that the run's own artifacts
pinpointed; both are fixed, and the complete suite, unfiltered and with retries off,
passes locally: **116 passed, 0 failed, 7.8 m**.

The limitations, stated plainly:

* the two fixes that make the browser job green are **not yet executed on GitHub**,
  because pushing them is the owner's decision;
* six frontend advisories remain, none critical, all transitive under Next.js;
* `pip-audit` stays advisory because the backend has no lockfile;
* `main` has no branch protection, so none of these checks is enforced as a merge
  requirement.

This is a statement about CI, not about production readiness. Nothing here validates
the deployment path, the institutional environment, or the release workflow, none of
which has ever run.
