# SCU — Academic Admission Phase 0: CI Probe Job

**Status:** proposed. The workflow below is not committed yet; it is added in the Phase 0 change,
together with the migration it tests. Until that migration exists the job would fail on its first
guard, so enabling it earlier would only add a red check.
**Companion:** `docs/scu-academic-admission-phase0-probe-pack.md` (the probes and the review
checklist).
**Applies to:** Phase 0 of `docs/scu-academic-admission-implementation-plan.md`.

---

## 1. What this job is for

The existing `CI` workflow already applies migrations to a fresh database and runs
`alembic check` in its backend job, but it does **not** run the constraint probes. The probes are the
only automated evidence that the trigger-only rules — `ADMITTED`-while-`ACTIVE`, immutability,
no-delete, the set-once pointer, the change-review guard — exist in a *migrated* database, because
the pytest fixtures build schema with `Base.metadata.create_all` and never create triggers.

This job therefore runs on exactly the changes that can break those rules:

- any file under `apps/api/alembic/**` (a new revision or an edit to an existing one),
- any model change under `apps/api/app/models/**`,
- the permission catalogue, because Phase 0 seeds new codenames,
- the probe pack itself, because the SQL lives in that document.

It is a **separate workflow**, not a job in `ci.yml`, for one reason: GitHub Actions has no
job-level path filter, and the trigger requirement is "on every migration change". A separate
workflow keeps the ~2-minute probe run off unrelated pull requests while leaving the existing
pipeline untouched.

---

## 2. Workflow definition

Add this as `.github/workflows/admission-phase0-probes.yml`.

```yaml
name: Admission Phase 0 probes

# Runs only when something that can change the migrated admission schema changes.
# The SQL under test lives in the probe pack, so edits to that document are a
# trigger too.
on:
  pull_request:
    paths:
      - "apps/api/alembic/**"
      - "apps/api/app/models/**"
      - "apps/api/app/permissions/constants.py"
      - "docs/scu-academic-admission-phase0-probe-pack.md"
      - ".github/workflows/admission-phase0-probes.yml"
  push:
    branches: [main]
    paths:
      - "apps/api/alembic/**"
      - "apps/api/app/models/**"
      - "apps/api/app/permissions/constants.py"
      - "docs/scu-academic-admission-phase0-probe-pack.md"
      - ".github/workflows/admission-phase0-probes.yml"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: admission-phase0-probes-${{ github.ref }}
  cancel-in-progress: true

env:
  PYTHON_VERSION: "3.11"
  PROBE_DOC: docs/scu-academic-admission-phase0-probe-pack.md
  EXPECTED_PROBES: "45"

jobs:
  probes:
    name: Phase 0 constraint probes (migrated scratch DB)
    runs-on: ubuntu-latest
    timeout-minutes: 15

    services:
      postgres:
        image: postgres:16-alpine
        env:
          # Disposable database. Synthetic credentials, no secret, no volume.
          POSTGRES_DB: school_portal_phase0_ci
          POSTGRES_USER: portal
          POSTGRES_PASSWORD: portal
        ports:
          # Same host port the local stack uses, so the probe document's
          # commands and this job share one URL shape.
          - 5433:5432
        options: >-
          --health-cmd "pg_isready -U portal -d school_portal_phase0_ci"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      ENVIRONMENT: testing
      DATABASE_URL: postgresql://portal:portal@localhost:5433/school_portal_phase0_ci
      STORAGE_BACKEND: local
      STORAGE_LOCAL_ROOT: /tmp/ci-probe-storage
      LOG_FORMAT: json

    defaults:
      run:
        working-directory: apps/api

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
          cache-dependency-path: apps/api/pyproject.toml

      - name: Install backend
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"

      - name: Ensure psql client
        # ubuntu-latest ships a PostgreSQL client; install only if it is absent.
        run: |
          psql --version || {
            sudo apt-get update
            sudo apt-get install -y postgresql-client
          }

      - name: Migrate, reverse and re-migrate an empty database
        # Proves the revision is reversible while every new table is empty, which
        # is the only condition under which the documented downgrade is allowed.
        run: |
          python -m alembic upgrade head
          python -m alembic downgrade -1
          python -m alembic upgrade head

      - name: Model and migration parity
        # Fails when a model change has no matching revision, so a table, CHECK,
        # index or FK cannot be added to the models and forgotten in the migration.
        run: python -m alembic check

      - name: Extract the probe script
        working-directory: .
        shell: bash
        run: |
          set -euo pipefail
          awk '/^-- BEGIN PHASE0 PROBES/{flag=1} flag{print} /^-- END PHASE0 PROBES/{flag=0}' \
            "$PROBE_DOC" > /tmp/phase0_probes.sql
          test -s /tmp/phase0_probes.sql
          probes="$(grep -cE "expect_(fail|ok)\('P-[0-9]{2}" /tmp/phase0_probes.sql || true)"
          echo "extracted probe calls: $probes"
          test "$probes" -eq "$EXPECTED_PROBES"
          echo "probe lines: $(wc -l < /tmp/phase0_probes.sql)"

      - name: Run probes against the migrated database
        working-directory: .
        shell: bash
        run: |
          set -o pipefail
          psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /tmp/phase0_probes.sql \
            2>&1 | tee /tmp/phase0-probes.log

      - name: Assert every probe passed
        working-directory: .
        shell: bash
        run: |
          set -euo pipefail
          if grep -q "FAIL P-" /tmp/phase0-probes.log; then
            echo "::error::At least one Phase 0 probe failed."
            grep "FAIL P-" /tmp/phase0-probes.log
            exit 1
          fi
          passed="$(grep -c "PASS P-" /tmp/phase0-probes.log || true)"
          echo "PASS count: $passed (expected $EXPECTED_PROBES)"
          test "$passed" -eq "$EXPECTED_PROBES"
          grep -q "Phase 0 probes complete" /tmp/phase0-probes.log

      - name: Upload probe log
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: phase0-probe-log
          path: /tmp/phase0-probes.log
          if-no-files-found: warn
          retention-days: 7
```

---

## 3. Why each step is there

| Step | What it catches |
|---|---|
| `install backend` | A revision that imports a module or type the project does not declare |
| `Ensure psql client` | A runner image change removing the client; without it the job would fail on a missing binary rather than a failed probe |
| `Migrate, reverse, re-migrate` | An irreversible upgrade, or a downgrade that drops objects a fresh database still needs |
| `alembic check` | Model/migration drift: a CHECK, index or FK added on the model but missing from the revision (or the reverse) |
| `Extract the probe script` | A broken begin/end marker, an empty extraction, or a truncated document — the job fails before pretending zero probes passed |
| `Run probes` | Any constraint, index, trigger or FK that is missing, too weak, or attached to the wrong object |
| `Assert every probe passed` | A psql run that exits 0 while the harness printed a failure (for example a future harness change), or a silent probe-count regression |
| `Upload probe log` | Failure diagnosis without re-running: the log holds `PASS`/`FAIL` labels and SQLSTATEs |

The job deliberately does not run `pytest`, the frontend, or the browser suite. Those are covered by
`ci.yml`; duplicating them here would make a migration-only change wait on unrelated work.

---

## 4. Expected behaviour

- **Before Phase 0 exists:** the workflow is not present. If it were added early, `alembic check`
  and the probe guard would fail with "Phase 0 schema is not applied", which is accurate but not
  useful. Add both in the same change.
- **On the Phase 0 change:** the job runs for roughly 90–150 seconds (image pull excluded on a warm
  cache), prints 45 `PASS` notices, ends with `Phase 0 probes complete`, and discards the transaction
  with `ROLLBACK`.
- **On a later migration edit:** the same run repeats. A new revision that weakens or omits a Phase 0
  object fails here even if `pytest` stays green.
- **On a model-only edit:** `alembic check` fails when the model gained a constraint that has no
  revision; the probes catch the case where a model edit changed a predicate that the database still
  enforces differently.

---

## 5. Rollout

1. Land the workflow file in the same pull request as the Phase 0 migration and its models.
2. Run it once manually (`workflow_dispatch`) and confirm 45 passes.
3. Add `Phase 0 constraint probes (migrated scratch DB)` to the branch-protection required checks
   for `main`, so a schema regression cannot merge on a green but unrelated pipeline.
4. Leave `ci.yml` unchanged; this workflow is additive.

If the team later prefers a single pipeline, the job can be copied into `ci.yml` behind a
changed-files detection step, but it would then run on every pull request unless that detection is
maintained. The separate path-filtered workflow is the lower-maintenance option and matches the
"only when migrations change" requirement.

---

## 6. Security and environment boundaries

- The PostgreSQL service is ephemeral, has synthetic credentials, and uses no volume; nothing
  survives the job.
- No secret, token, student record or institutional extract is referenced. Probe fixtures are
  generated (`TEST-*`, `phase0-*@example.test`).
- The job never starts the development stack, never touches Docker volumes, and never contacts the
  isolated production-verification environment.
- `permissions: contents: read` matches the existing workflow; the job needs nothing else.
- The probe log contains only synthetic identifiers and SQLSTATEs; it is retained for 7 days.

---

## 7. Cost and ownership

- One `ubuntu-latest` runner, one PostgreSQL 16 service, no application image build.
- Typical wall time: 90–150 seconds after dependency cache warm-up.
- Owner: whoever owns the migration in the Phase 0 change; after that, the backend maintainer on
  call for CI.

No workflow, migration, database or environment was changed to produce this description.
