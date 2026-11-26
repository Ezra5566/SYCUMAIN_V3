# SYCUMAIN V3 — CI/CD setup and release workflow

**Status:** workflows written and verified locally; **not committed, not pushed, not
deployed.** GitHub Actions has not executed them yet.
**Date:** 2026-11-26
**Scope:** `.github/workflows/`, `.github/dependabot.yml`, the pnpm workspace file,
the OpenAPI contract, lint fixes, and this document.

---

## 1. What already existed

The repository `Ezra5566/SYCUMAIN_V3` (public, default branch `main`) already had
one workflow — `.github/workflows/ci.yml` — contributed during the Phase 10
stabilisation work. It defined five jobs:

| Job | Ran |
|---|---|
| `Backend (tests, lint, migrations)` | ruff, `alembic upgrade head`, `alembic check`, `import app.main`, `pytest` |
| `API contract (OpenAPI current)` | compares an exported OpenAPI document with `apps/web/openapi.json` |
| `Frontend (types, i18n, build)` | `pnpm install --frozen-lockfile`, typecheck, lint, `i18n:check`, `next build` |
| `Docker images (both artifacts build)` | builds `Dockerfile.api` and `Dockerfile.web --target production` |
| `Browser E2E (isolated stack)` | `./scripts/e2e.sh` against `docker-compose.test.yml` |

Supporting infrastructure that already existed and was **reused, not replaced**:
`Makefile` targets, `docker-compose{,.prod,.test}.yml`, `infra/docker/Dockerfile.{api,web}`,
`.dockerignore`, `scripts/e2e.sh`, `apps/api/tests/conftest.py` (refuses any database
that is not `localhost/school_portal_test*`), `apps/web/scripts/check-i18n.mjs`, and
the twelve Playwright specs under `apps/web/e2e/`.

### What actually happened on GitHub

The repository has **exactly one** workflow run so far: run
[45764076190](https://github.com/Ezra5566/SYCUMAIN_V3/actions/runs/45764076190),
on the push of `c2f5c5b` to `main`. It **failed**, 4 of 5 jobs red:

| Job | Result | First failing step |
|---|---|---|
| Backend | ✗ failure (28 s) | `Lint` — 10 ruff violations |
| API contract | ✗ failure (26 s) | `Fail when the contract is stale` |
| Frontend | ✗ failure (13 s) | `Install` — `ERROR packages field missing or empty` |
| Browser E2E | ✗ failure (9 s) | `Install` — same pnpm error |
| Docker images | ✓ success (134 s) | — |

So: the pipeline was well-designed but **had never been green**, and three of the
four failures were template defects, not code defects.

### Root causes and their fixes

1. **`ERROR packages field missing or empty`** (Frontend, E2E).
   `apps/web/pnpm-workspace.yaml` existed without a `packages:` key. pnpm requires
   that key whenever the file is present and aborts before installing anything.
   Fixed by adding `packages: ["."]`.
   A second, latent defect surfaced while verifying: the build allow-list was
   declared in `package.json` under `pnpm.onlyBuiltDependencies`, a location pnpm
   10+ no longer reads. pnpm 12 turns the resulting unapproved scripts into a hard
   error (`ERR_PNPM_IGNORED_BUILDS`). The allow-list now lives in
   `pnpm-workspace.yaml` under `allowBuilds` — the shape `pnpm approve-builds`
   itself writes — and the dead `pnpm` field was removed from `package.json`.

2. **`Fail when the contract is stale`** (Contract).
   The timetable work added six endpoints that were never exported into the
   committed document. `apps/web/openapi.json` was regenerated: 187 → 193 paths.

3. **`Lint`** (Backend). Ten ruff violations (unsorted imports, a Yoda condition,
   nested `if`/`with`, a type-only import). Fixed properly with `ruff --fix` plus
   three manual edits — no rule was disabled and no `noqa` was added.

---

## 2. What is missing, and what changed

| Gap | Change |
|---|---|
| Pipeline had never run green | The three blocking defects above are fixed |
| No locale-route verification | New `apps/web/scripts/check-locale-routes.mjs`, run as `pnpm check:locales` |
| No Arabic RTL check in CI | Same script: asserts `dir="rtl"` for `ar`, `ltr` for the rest |
| No Compose validation | `docker compose --env-file … -f docker-compose.prod.yml config` in the `images` job |
| No check that images are secret-free | The `images` job inspects both images for `.env`, `.git`, `*.pem`, `id_rsa*`, `*.key` |
| No check that `.env.production.example` documents required variables | Same job asserts `SECRET_KEY`, `APP_ORIGIN`, `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`, `SITE_ADDRESS` |
| No dependency-advisory reporting | New `security` job (+ Dependabot configuration) |
| No check that no real `.env` is tracked | Same job |
| E2E ran on every documentation change | New `changes` job; `e2e` is skipped for docs-only diffs |
| Actions floated on major tags, and were deprecated on Node 20 | All pinned to exact commits on current majors |
| No release workflow | New `.github/workflows/release.yml` |

---

## 3. The CI workflow

`.github/workflows/ci.yml` — triggers: `push` to `main`, every `pull_request`,
`workflow_dispatch`. `permissions: contents: read`. Concurrency cancels a
superseded run on the same ref. No secret is referenced anywhere, and every
database is a throwaway `postgres:16-alpine` service or a disposable Compose stack.

### `changes`
`git diff` against the PR base (or `github.event.before`). Emits `code=true|false`.
A missing/unknown base — new branch, force-push, manual run — is treated as a code
change, so nothing is silently skipped. `docs/**`, `*.md` and issue-template paths
alone yield `code=false`.

### `backend`
What it proves: the code lints, the schema builds from nothing, model and
migration agree, the app imports with a valid configuration, and the suite passes.
Steps: `ruff check app tests tools` → `alembic upgrade head` (fresh, empty database)
→ `alembic check` → `python -c "import app.main"` → `pytest -q`.
Database: service container `school_portal_test_v2` on `localhost:5433`, synthetic
`portal:portal`. `conftest.py` independently refuses any URL that is not
`localhost/school_portal_test*`, so CI cannot reach V1 or an institutional database.

### `contract`
Exports the live OpenAPI document and compares it to `apps/web/openapi.json` as
parsed JSON (key order and indentation are free to differ). Prints the offending
command on failure.

### `frontend`
`pnpm install --frozen-lockfile` → `pnpm typecheck` → `pnpm lint` → `pnpm i18n:check`
(2 658 keys × 5 locales, 225 error codes) → `pnpm build` with a synthetic
`NEXT_PUBLIC_API_URL` → `pnpm check:locales`.

`check-locale-routes.mjs` starts the server that `next build` produced (the
standalone one, falling back to `next start`), waits for it to answer, then requests
`/{en,zh,fr,ru,ar}/login` and asserts status 200, `<html lang>`, `<html dir>`, and
that no raw translation key leaked into the HTML. It exits non-zero on any failure.

### `images`
Builds `Dockerfile.api` and `Dockerfile.web --target production` with `load: true`,
then (a) inspects both for environment files, `.git` and key material, (b) asserts
the API image has no `/app/tests`, and (c) validates `docker-compose.prod.yml`
against `.env.production.example` and asserts the template still documents the five
variables the composition requires.

### `security`
(a) Fails if any `.env*` file other than `*.example`/`*.sample`/`*.template` is
tracked. (b) Backend advisory: `pip-audit --local --skip-editable` over the
installed environment — **advisory**, see §9. (c) `pnpm audit --prod
--audit-level critical` — **blocking**; currently 0 critical. (d) Full
`pnpm audit --prod` report — **advisory**.

### `e2e`
Runs only when `changes.outputs.code == 'true'`. Reuses `./scripts/e2e.sh`
unchanged: its own project (`school-portal-v3-e2e`), its own ports
(5436/8002/3002), readiness polling on `/ready` and a real login page, teardown with
volumes on success, failure or interrupt. Specs cover login, anonymous redirect,
wrong credentials, logout invalidation, student-directory deny for students, role
navigation, academics and timetable, five-locale rendering and RTL layout.

---

## 4. The release workflow

`.github/workflows/release.yml` — triggers: tag `v*`, and `workflow_dispatch` only.
`permissions: contents: read` at workflow level; each job requests the minimum it
needs (`packages: write` for the build, `contents: write` for the release).

Inputs on dispatch: `version` (semver, required), `environment` (`staging` |
`production`), `rollback_to`, `run_migrations` (default `false`).

| Job | Runs when | Does |
|---|---|---|
| `build` | tag push, or dispatch without `rollback_to` | builds and pushes both images to GHCR, writes and uploads `release-manifest.json` |
| `migrate` | dispatch, `run_migrations=true`, no rollback, `DEPLOY_ENABLED` | `alembic upgrade head` **only**, on the approved environment |
| `deploy` | dispatch, build succeeded (or a rollback), `DEPLOY_ENABLED` | `compose pull` + `up -d` for the chosen tag, then `GET /ready` |
| `release` | tag push | GitHub Release with the manifest attached |

Nothing here runs on a merge to `main`.

### Artifact naming and versioning

```
ghcr.io/ezra5566/sycumain_v3-api:<version>     # e.g. 3.1.0
ghcr.io/ezra5566/sycumain_v3-api:<commit12>    # immutable, same image
ghcr.io/ezra5566/sycumain_v3-web:<version>
ghcr.io/ezra5566/sycumain_v3-web:<commit12>
```

Two tags per image: the human version and the exact commit. Neither is ever
overwritten; a rollback names one of them. `release-manifest.json` records the
version, commit, build time and both image digests, and is retained 90 days as a
workflow artifact and attached to the GitHub Release.

### Environment separation

| Environment | Images | Database | Approval |
|---|---|---|---|
| development | built locally by `docker-compose.yml` | dev stack on 5435 | none |
| CI / test | built per run, never pushed | disposable containers (5433, 5436) | none |
| staging | GHCR, version tag | its own Compose stack | `staging` environment reviewers |
| production | GHCR, version tag | its own Compose stack | `production` environment reviewers |

Separation is enforced by three independent things: the GitHub environment
(approvals + scoped secrets), the `DEPLOY_ENABLED` repository variable, and the
fact that `NEXT_PUBLIC_API_URL` / `APP_ORIGIN` are per-environment values baked at
build time.

### Deployment approval

1. A maintainer runs **Release** with `environment=production`.
2. `build` publishes images (no host access).
3. `migrate`, if requested, and `deploy` both declare
   `environment: production`, so **GitHub pauses them until a required reviewer
   approves**. Until those reviewers are configured in repository settings, there
   is no approval gate — see §7.
4. `deploy` finishes by polling `https://<APP_ORIGIN>/ready`.
5. Any deployment is recorded in the run summary and in the GitHub Release.

If `DEPLOY_ENABLED` is not `true`, the deployment jobs are **skipped**, visibly.
They never report success without having done the work.

### Rollback

Rollback does not rebuild and does not touch the schema:

1. Run **Release** with `environment=<env>` and `rollback_to=<previous version or
   commit12>`. `build` is skipped; `deploy` pulls that immutable tag and restarts.
2. Verify `GET /ready`.
3. If the bad release carried a migration, prefer a **new forward revision**.
   Several revisions refuse `alembic downgrade` while institutional rows exist, by
   design (see `docs/deployment-v3.md` §8).
4. `scripts/restore.sh --live` remains the last resort, not the first.

---

## 5. Required GitHub repository settings

None of these were changed — they need explicit approval.

### Secrets (`Settings → Secrets and variables → Actions → Secrets`)

| Name | Used by | Purpose |
|---|---|---|
| `DEPLOY_HOST` | `migrate`, `deploy` | target host |
| `DEPLOY_USER` | `migrate`, `deploy` | SSH user |
| `DEPLOY_SSH_KEY` | `migrate`, `deploy` | private key for that host |

`GITHUB_TOKEN` is provided automatically; no other secret exists. Set them per
environment (`staging`, `production`) so each environment only sees its own host.

### Variables (`… → Variables`)

| Name | Example | Purpose |
|---|---|---|
| `DEPLOY_ENABLED` | `false` | master switch; deployment jobs are skipped unless `true` |
| `DEPLOY_PATH` | `/opt/sycumain` | directory holding `docker-compose.prod.yml` on the host |
| `APP_ORIGIN` | `https://portal.example.edu` | public origin; also the web build argument and `/ready` target |

`APP_ORIGIN` is also a legitimate *runtime* requirement of the application itself
(baked into the client bundle). The complete runtime set is documented in
`.env.production.example` and enforced by `docker-compose.prod.yml` with `${VAR:?}`
guards: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_APP_USER`,
`POSTGRES_APP_PASSWORD`, `SECRET_KEY`, `APP_ORIGIN`, `SITE_ADDRESS`.

### Environments

Create `staging` and `production` (`Settings → Environments`), then for
`production`: add **Required reviewers** (at least one, and not the person who
triggers the run), restrict which branches may deploy, and add the three deployment
secrets to that environment rather than to the repository.

### Branch protection / ruleset for `main`

Currently `main` is **unprotected** (`protected: false`, no rulesets, no required
checks), so any push lands directly. Recommended ruleset:

- require a pull request before merging, with **≥1 approving review**;
- dismiss stale approvals on new commits;
- require review from someone other than the last pusher;
- require these status checks: `Backend (tests, lint, migrations)`,
  `API contract (OpenAPI current)`, `Frontend (types, i18n, build, locales)`,
  `Docker images and production composition`, `Security (advisories)`,
  `Browser E2E (isolated stack)` (mark E2E *not* required if it is too slow for
  every PR — but then it must run before a tag);
- block force-pushes and deletions;
- optionally require signed commits.

### Code security

Already enabled on the repository: secret scanning, secret-scanning push
protection. Still **disabled**: Dependabot security updates. Enabling them makes
the `dependabot.yml` in this change produce upgrade PRs.

---

## 6. Local equivalents

Every gate is a command a developer already has:

```bash
make lint-api            # ruff check app tests tools
make test-api            # pytest against the disposable test database (5434)
make migrate-check       # alembic check
make typecheck           # tsc --noEmit
make lint                # next lint
make i18n                # translation parity across five locales
make locales             # five locale routes + Arabic RTL (needs `make build`)
make build               # next build
make e2e                 # Playwright against an isolated, disposable stack
make prod-config         # docker-compose.prod.yml resolves
```

Backend migrations against a scratch database, exactly as CI does:

```bash
cd apps/api
export DATABASE_URL=postgresql://portal:portal@localhost:5434/school_portal_test_v2
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic check
```

Contract regeneration after changing an endpoint:

```bash
cd apps/api && .venv/bin/python tools/export_openapi.py ../web/openapi.json
```

Dependency advisories:

```bash
cd apps/api && .venv/bin/python -m pip install pip-audit && .venv/bin/python -m pip_audit --local --skip-editable
cd apps/web && pnpm audit --prod
```

---

## 7. Verified locally vs executed on GitHub

| Check | Locally | On GitHub Actions |
|---|---|---|
| `ruff check app tests tools` | ✅ clean | not yet |
| `pytest` affected suites (38 + 53 passed, 1 skipped) | ✅ | not yet |
| `alembic upgrade head` / `alembic check` | ✅ dev DB already at head, `alembic check` clean | not yet |
| OpenAPI contract | ✅ identical after regeneration | not yet |
| `pnpm install --frozen-lockfile` | ✅ in `apps/web` and inside the Docker build | not yet |
| `pnpm typecheck` , `pnpm lint`, `pnpm i18n:check` | ✅ (one pre-existing font warning) | not yet |
| `pnpm build` | ✅ | not yet |
| `pnpm check:locales` | ✅ 5/5, Arabic `dir=rtl` | not yet |
| `docker build` web, `--target production` | ✅ | ✅ (before this change) |
| `docker build` api | ✅ | ✅ (before this change) |
| `docker compose … config` (prod) | ✅ | not yet |
| `pnpm audit --prod --audit-level critical` | ✅ 0 critical | not yet |
| Image secret inspection (both images) | ✅ executed: clean | not yet |
| API image contains no `/app/tests` | ✅ executed: absent | not yet |
| `./scripts/e2e.sh` | not run in this task | failed previously at `Install` |
| `release.yml` | ⚠️ YAML parses, no run performed | not yet |
| Action SHAs resolve | ✅ resolved from upstream tags today | — |

**No workflow in this change has been executed by GitHub Actions.** The first real
run will be the first push that includes it.

---

## 8. Known limitations

1. **No Python lockfile.** `pyproject.toml` uses lower-bound ranges, so backend
   resolves are not reproducible and `pip-audit` can only report the current
   resolution. That is why the backend audit is advisory. Adding a lock
   (`uv lock` or `pip-tools`) would make it blocking and reproducible.
2. **6 known frontend advisories** (3 high, 3 moderate) in Next.js's transitive
   tree (`source-map-js`, `postcss`). Clearing them means a coordinated Next.js
   upgrade; Dependabot proposes it. CI blocks only on *critical*.
3. **No deployment target exists.** `release.yml` is complete but inert until
   `DEPLOY_ENABLED`, the environments, and the SSH secrets are configured. It has
   never executed.
4. **`ubuntu-26.04` runners** force Node-20 actions onto Node 24 and warn. All
   actions are pinned to current majors that target Node 24, which removes the
   warning; `NODE_VERSION` stays 20 because the web image is `node:20-alpine`.
5. **Node 20 is end-of-life upstream.** The image base and CI matrix should both
   move to Node 22 as a separate, deliberate change (it also affects
   `Dockerfile.web`).
6. **Approval gates are a repository setting, not a workflow property.** Without
   required reviewers on the `production` environment, `deploy` runs as soon as
   `DEPLOY_ENABLED=true`. This document is the only thing pointing that out.
7. **Image secret inspection is a filename scan**, not an entropy scan. It catches
   a baked `.env` or key file; it would not catch a secret pasted into a source
   file. GitHub secret scanning covers the repository side. Its scope is `/app`,
   not the whole filesystem: a first draft scanned `/` and reported the base
   image's own `/etc/ssl/cert.pem`, which would have failed CI permanently.
8. **No branch protection is configured**, so the pipeline is advisory until the
   ruleset in §5 is applied.
9. **The `changes` job compares commit ranges**, so a docs-only PR still runs the
   five quick jobs; only the browser suite is skipped.
10. **The E2E suite was not run in this task.** It failed previously at `Install`;
    the install defect is fixed and verified separately, but the full suite has not
    been re-run end to end.
11. **`tools/export_openapi.py` and the committed artifact disagree on formatting.**
    The tool writes `indent=2`; the committed `apps/web/openapi.json` is a single
    compact line. CI compares parsed JSON so both pass, and this change kept the
    existing compact style to hold the diff to one line. Regenerating with the
    documented command will therefore produce a ~30 000-line diff until the two
    are reconciled — worth a small follow-up: either emit compact from the tool or
    re-commit the file pretty-printed once.

---

## 9. Change inventory

Modified:

- `.github/workflows/ci.yml` — hardened (see §3)
- `apps/web/pnpm-workspace.yaml` — `packages` + `allowBuilds`
- `apps/web/package.json` — removed the dead `pnpm.onlyBuiltDependencies` field; added `check:locales`
- `apps/web/openapi.json` — regenerated (187 → 193 paths)
- `apps/api/app/audit/service.py`, `apps/api/app/routers/academic.py`,
  `apps/api/app/services/academic.py`, `apps/api/tools/seed_load.py`,
  `apps/api/tests/test_audit_history.py`,
  `apps/api/tests/test_audit_immutability.py`,
  `apps/api/tests/test_institutional_timetable.py` — lint compliance only
  (import order, nested `if`/`with`, type-only import); no behaviour change
- `Makefile` — `locales` target

Added:

- `.github/workflows/release.yml`
- `.github/dependabot.yml`
- `apps/web/scripts/check-locale-routes.mjs`
- `docs/v3-ci-cd-setup-and-release-workflow.md` (this file)
