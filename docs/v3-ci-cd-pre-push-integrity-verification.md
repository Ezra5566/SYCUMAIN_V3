# V3 — CI/CD Pre-Push Integrity Verification

**Date:** 2026-11-26
**Repository:** `Ezra5566/SYCUMAIN_V3` (local `SYCUMAIN_V2/`, branch `main`)
**HEAD verified:** `c2f5c5b2c3b3fc02094a9be3bee44f79ba5166bf`
**Purpose:** prove that the current repository still contains the certified Phase 10
implementation before any push or GitHub repository configuration change.
**Mode:** read-only. Nothing was staged, committed, pushed or deployed. No Git history was
rewritten. No existing database was reset or migrated. V1 was not opened for writing, and
no V1 file, container or schema was touched.

---

## Verdict summary

| # | Check | Result |
|---|---|---|
| 1 | Relationship between `8467300` and `c2f5c5b` | **RECONCILED** — `8467300` is the direct parent; the Phase 10 tree was committed, not discarded |
| 2 | All Phase 10 application changes present | **VERIFIED** — every item in the Phase 10 change classification exists at HEAD |
| 3 | Migration `d1e4a7b9c2f5` exists and is registered | **VERIFIED** — in the chain, single head, applies cleanly to an empty database |
| 4 | Audit immutability triggers and application-role protections | **VERIFIED and empirically demonstrated** (rejects a superuser) |
| 5 | Migration fail-closed protections | **VERIFIED** — V1 refused, production confirmation enforced |
| 6 | ClamAV production service and scanner integration | **VERIFIED by configuration inspection**; not re-run against a live daemon |
| 7 | Phase 10 performance optimisations and audit-history changes | **CODE VERIFIED**; performance numbers not re-measured |
| 8 | Previous engineering reports and evidence | **VERIFIED** — 32 documents, 16 evidence files, all present |
| 9 | Timetable implementation and its uncommitted changes | **VERIFIED** — committed in `c2f5c5b`, no timetable logic in the current diff |
| 10 | CI/CD modifications did not weaken security, permissions or tests | **VERIFIED** — hardening only; one assertion reordered with identical semantics |

Two corrections are required before pushing, and one operational step. They are listed in
[Corrections required before push](#corrections-required-before-push). Neither is a loss of
Phase 10 work; both are defects in the CI/CD additions and in one Phase 10 wording.

Final conclusion: **[SAFE AFTER SPECIFIC CORRECTIONS](#conclusion)**.

---

## 1. Relationship between `8467300` and `c2f5c5b`

The two reported states are not divergent. They are consecutive commits on one linear
branch.

```
c2f5c5b2c3b3fc02094a9be3bee44f79ba5166bf 8467300fcb09efa3ea1d5735df1b6e2c6c2b0473
```

`git rev-list --parents -n 1 c2f5c5b` prints exactly one parent, and it is `8467300`.
`git merge-base --is-ancestor 8467300 c2f5c5b` succeeds; the reverse does not.

| | Phase 10 baseline | Current HEAD |
|---|---|---|
| Commit | `8467300` | `c2f5c5b` |
| Committer date | 2026-11-24 08:05:45 +0800 | 2026-11-26 13:41:47 +0800 |
| Subject | `feat: activate migrated accounts instead of issuing passwords` | `v3 of sycumain first stable backend version` |

History is five commits, `30fa654 → f8ad3e2 → be3b24f → adfea31 → 8467300 → c2f5c5b`, with
no branches other than `main`, no tags, no stashes and no merge commits. The reflog shows
`c2f5c5b` created by `commit` and then three cosmetic `Branch: renamed refs/heads/main to
refs/heads/main` entries. Nothing was reset or discarded.

### Reconciling the file counts

| Measure | Value |
|---|---|
| `8467300..c2f5c5b` | **154 files changed, +18,296 / −560** |
| Status letters | **81 added, 73 modified, 0 deleted, 0 renamed** |
| Reported Phase 10 working tree | 54 modified, 50 untracked |
| Current working tree | **16 entries** (12 modified, 4 untracked), **0 staged** |

The reported 54 + 50 = 104 is a *working-tree snapshot* of Phase 10, not the commit. It
under-counts for two verifiable reasons:

1. **Untracked directories collapse.** Default `git status --porcelain` reports an
   untracked directory as one entry. The 50 untracked entries included whole new trees —
   `docs/evidence/timetable-comparison/` (7 files) and `docs/evidence/timetable-completion/`
   (8 files), `scripts/load/`, `apps/web/scripts/`, `infra/docker/`, `infra/caddy/` — so 50
   entries covered 81 files.
2. **Work continued between the snapshot and the commit.** Phase 10 §I.3 explicitly records
   that a large body of pre-existing untracked work had to be `git add`-ed for the baseline
   (both Compose production files, the two Phase 7 migrations, the provisioning script, the
   three new test modules, and the evidence PNGs).

The direction of the discrepancy matters: the commit is a **superset** of the reported
snapshot, not a subset. `0 deleted` in the diff is the decisive fact — committing cannot
have removed any Phase 10 file.

---

## 2. All Phase 10 application changes are present

Each row of the Phase 10 change classification (§I.1 of
`v3-phase-10-stabilization-and-release-hardening-report.md`) was checked against the actual
tree, not against the report.

| Phase 10 category | Files | Present at HEAD |
|---|---|---|
| 1. Audit integrity | `app/database/audit_immutability.py`, `app/models/audit.py`, `alembic/versions/d1e4a7b9c2f5_*`, `scripts/provision-db-roles.sh` | ✅ all four |
| 2. Historical records | `app/audit/service.py`, `app/audit/__init__.py`, `app/routers/{students,housing,academic,immigration}.py`, `app/services/immigration.py` | ✅ all seven |
| 3. Performance | `app/models/academic.py`, `app/services/academic.py`, `app/auth/service.py` | ✅ all three |
| 4. Migration safety | `app/database/migration_guard.py`, `alembic/env.py` | ✅ both |
| 5. Deployment / scanning | `docker-compose.prod.yml`, `.env.production.example` | ✅ both |
| 6. Tests | `tests/test_audit_immutability.py`, `tests/test_audit_history.py`, `tests/test_migration_guard.py`, `tests/test_platform.py` | ✅ all four |
| 6b. Localisation | `apps/web/messages/{en,zh,fr,ru,ar}.json` | ✅ all five (modified in the commit) |
| 7. Documentation | the Phase 10 report | ✅ 43,025 bytes |

No Phase 10 category is missing and no unexpected deletion exists in the commit.

---

## 3. Migration `d1e4a7b9c2f5`

**Exists:** `apps/api/alembic/versions/d1e4a7b9c2f5_audit_log_immutability.py`.

**Registered:** `down_revision = "c4d7e91b2f68"`, and `f3b7c2d9e6a1` declares
`down_revision = "d1e4a7b9c2f5"`. `alembic heads` reports a **single head**,
`f3b7c2d9e6a1`, across all 32 revision files — so the chain is linear and the Phase 10
revision is an interior link, not an orphan.

**Applies cleanly — proven, not asserted.** A disposable database
`school_portal_scratch_verify` was created on the local PostgreSQL server, migrated from
empty, inspected, and dropped:

```
CREATE DATABASE
Running upgrade c4d7e91b2f68 -> d1e4a7b9c2f5, Phase 10: make ``audit_logs`` append-only in the database.
Running upgrade d1e4a7b9c2f5 -> f3b7c2d9e6a1, late enrollment authorization
--- resulting revision: f3b7c2d9e6a1   (== head)
--- triggers: audit_logs_reject_delete / audit_logs_reject_truncate / audit_logs_reject_update
--- alembic check: "No new upgrade operations detected."
DROP DATABASE
```

`alembic check` reporting no pending operations on a freshly migrated database additionally
proves **model/migration parity**: the SQLAlchemy metadata and the 32-revision chain agree.

`upgrade()` issues only `CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS`,
`CREATE TRIGGER` and `REVOKE`. It contains no `DROP TABLE`, no `DELETE`, no `UPDATE`, no
`TRUNCATE` and no backfill. `downgrade()` removes the triggers and the function only; audit
rows are never dropped.

---

## 4. Audit immutability triggers and application-role protections

### 4.1 The trigger rejects mutation by a superuser

Verified on the freshly migrated disposable database. The connection role `portal` is
`rolsuper = t` — the harshest possible test case, because a superuser bypasses `GRANT`s:

```
portal|t
insert audit_logs (action='verify.probe')            -> INSERT 0 1   (insert permitted)

UPDATE audit_logs SET action='tampered' ...
  ERROR:  audit_logs is append-only: UPDATE is not permitted
  CONTEXT: PL/pgSQL function audit_logs_reject_mutation() line 3 at RAISE

DELETE FROM audit_logs ...
  ERROR:  audit_logs is append-only: DELETE is not permitted

TRUNCATE audit_logs
  ERROR:  audit_logs is append-only: TRUNCATE is not permitted

row survived: 1
```

Three triggers exist with the intended scope, confirmed by `pg_get_triggerdef` on the
database at head:

| Trigger | Definition |
|---|---|
| `audit_logs_reject_update` | `BEFORE UPDATE ... FOR EACH ROW` |
| `audit_logs_reject_delete` | `BEFORE DELETE ... FOR EACH ROW` |
| `audit_logs_reject_truncate` | `BEFORE TRUNCATE ... FOR EACH STATEMENT` |

`TRUNCATE` is correctly statement-level (PostgreSQL does not support row-level `TRUNCATE`
triggers). The function raises with `ERRCODE = insufficient_privilege` (SQLSTATE 42501).

### 4.2 One precise correction to the Phase 10 wording

On the database at head, `information_schema.role_table_grants` still shows:

```
DELETE|portal    TRUNCATE|portal    UPDATE|portal
```

This is **not** a defect, but the Phase 10 report's phrasing is imprecise. `install_statements()`
runs `REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON audit_logs FROM PUBLIC`. `PUBLIC` is
not the owner: a table owner retains its own privileges regardless of a `PUBLIC` revoke, and a
superuser ignores them entirely. So:

* the `REVOKE` closes the door for ordinary roles that inherited `PUBLIC` grants;
* it does **not** and cannot remove the owning role's rights;
* the **trigger is the primary control**, which is exactly why it is installed on both the
  migration path and the `after_create` model path.

The production answer to the owner problem is the `provision-db-roles.sh` role split, and the
Phase 10 report already says so. Only the sentence implying the revoke alone constrains the
application connection needs tightening.

### 4.3 Application-role protections (inspected, not executed)

`scripts/provision-db-roles.sh` was read in full and **not executed** in this pass (executing
it creates a persistent cluster role; that is a deployment action, not a verification one).
It enforces:

* refusal when `POSTGRES_APP_USER == POSTGRES_USER`, so the grants cannot be proven against
  the owner;
* `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS` on every run (also the
  password-rotation path);
* `REVOKE TRUNCATE ON ALL TABLES` — no table in the schema can be emptied by the API role;
* `REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON audit_logs`, then `GRANT SELECT, INSERT`;
* `ALTER DEFAULT PRIVILEGES` so tables created by future migrations are not left unreadable.

And the wiring requires it: `docker-compose.prod.yml` sets the API's `DATABASE_URL` to
`${POSTGRES_APP_USER:?...}:${POSTGRES_APP_PASSWORD:?...}`, so a production bring-up cannot
silently fall back to the owning superuser. The `provision-roles` service is a one-shot
`tools` profile step, documented as running after `migrate` and before rolling the API.

### 4.4 Local database drift (operational finding)

| Database | Revision | Audit triggers |
|---|---|---|
| `localhost:5435/school_portal_v2` | `f3b7c2d9e6a1` (= head) | present (3) |
| `localhost:5434/school_portal_v2` (**the default** when `DATABASE_URL` is unset) | `a7c1e9b25d40` — 5 revisions behind | **absent (0)** |
| `localhost:5434/school_portal_test_v2` | no `alembic_version` (built by `create_all`) | installed by the model `after_create` hook |

Consequence: running `alembic check` with no environment set fails with `Target database is
not up to date`. That is **database state, not repository state** — the same command passes on
the freshly migrated database (§3). It also means the default development database does not
currently carry the migration-installed trigger; it relies on the model hook, which only fires
when the table is created. Anyone re-verifying §4 must either set `DATABASE_URL` to the
database at head or run `alembic upgrade head` first, otherwise the trigger check will read as
a false negative.

---

## 5. Migration fail-closed protections

Three layers, all confirmed by execution at HEAD.

**Static target guard** (`app/database/migration_guard.py`, called from `alembic/env.py`
before any connection opens):

```
DATABASE_URL=...localhost:5433/school_portal  (V1)  -> refused:
  MigrationTargetError: Refusing to migrate database 'school_portal': that is the V1
  reference installation. V3 migrations must run against 'school_portal_v2' (development)
  or the database named in MIGRATION_CONFIRM (production).
```

`FORBIDDEN_DATABASES = {school_portal, postgres, template0, template1}`; non-production
targets must match `^school_portal_[a-z0-9_]+$` or be listed in
`MIGRATION_ALLOWED_DATABASES`; production requires `MIGRATION_CONFIRM` to equal the database
name exactly. Ports are deliberately not part of the decision.

**Runtime identity check** — after connecting,
`verify_runtime_identity()` asserts `current_database()` equals the URL's database, and that
any recorded `alembic_version` is a revision this repository defines (so V1's `c7d9e1f3a5b7`
is refused even if the name check were bypassed).

**Production settings validator** fires even earlier and refuses to construct settings at all
for an insecure production configuration. Exercising the production path without the full set
of hardened variables produced:

```
Refusing to start with an insecure production configuration: DEBUG must be false ...
MALWARE_SCANNER=dev-clean is forbidden in production; use clamav;
DATABASE_URL must not use the documented portal:portal credentials;
CORS_ORIGINS must contain only https:// origins; ...
```

**Test evidence:** `tests/test_migration_guard.py` + `tests/test_audit_immutability.py`
→ **26 passed in 2.08s** on `school_portal_test_v2`.

**Minor pre-existing limitation (not caused by this work):** offline DDL generation,
`alembic upgrade head --sql`, aborts at revision `9a1f2b3c4d5e` with
`AttributeError: 'NoneType' object has no attribute 'fetchall'` — that revision reads
existing rows (`op.get_bind().execute(...).fetchall()`), which has no meaning in offline mode.
CI and every documented path use online mode, so this affects only someone expecting an
offline SQL script. Worth a sentence in the deployment doc; not a blocker.

---

## 6. ClamAV production service and scanner integration

Configuration is complete and internally consistent:

* `docker-compose.prod.yml` defines a `clamav` service (`clamav/clamav:stable`,
  `platform: ${CLAMAV_PLATFORM:-linux/amd64}`, `CLAMAV_NO_FRESHCLAM: "false"`).
* Signature state lives on the named volumes `clamav_db` and `clamav_run`, so a restart does
  not re-download ~200 MB of signatures and — more importantly — cannot serve an empty
  signature set while the first download completes.
* The healthcheck is `clamdcheck.sh` (a real daemon PING), not a port probe, with a 300 s
  `start_period`. A container that is running without signatures is never reported healthy.
* The API declares `depends_on: clamav: condition: service_healthy`, and forwards
  `CLAMAV_HOST` (default `clamav`), `CLAMAV_PORT` (3310) and `CLAMAV_TIMEOUT_SECONDS` (10).
  The comment records the concrete failure this avoids: without forwarding, the API looks for
  `clamav` inside its own container and every upload fails with `SCANNER_UNAVAILABLE` (503).
* `MALWARE_SCANNER: ${MALWARE_SCANNER:-clamav}` — unset means *scan*, not "accept
  everything".

The scanner implementation (`app/services/malware_scan.py`) speaks ClamAV's `zINSTREAM`
protocol over TCP: `zINSTREAM\0`, 1 MiB length-prefixed chunks, zero-length terminator, and a
bounded response read. Its fail-closed properties:

| Condition | Result | Caller outcome |
|---|---|---|
| connection error / timeout (`OSError`, `TimeoutError`) | `FAILED` — "scanner unavailable" | 503 |
| unrecognised response text | `FAILED` | 503 |
| `... FOUND` | `INFECTED` | 422 |
| `... OK` | `CLEAN` | stored |
| backend unset/`disabled` | `FAILED` | 503 |
| `dev-clean` outside development | `FAILED` | 503 |
| `eicar-test` outside testing | `FAILED` | 503 |

`dev-clean` is additionally refused outright by the production settings validator (§5), so
the "no inspection performed" backend cannot be selected in production by any route.

**Not verified in this pass:** an end-to-end scan against a live `clamd`. Phase 10 §F.3 records
that it was verified against a real daemon, including a known-good and an EICAR upload. That
evidence was not re-run here, and this report does not claim it was.

---

## 7. Phase 10 performance optimisations and audit-history changes

The three optimisations are present as *code*, each carrying the reasoning that motivated it.

| Optimisation | Location | Confirmed |
|---|---|---|
| `ClassSection` no longer eager-loads `attendance_records`, `enrollments`, `timetable_entries`, `assessments` | `app/models/academic.py:338-364`, with a comment explaining that these four collections materialised >5,000 objects per class-list request and that `enrolled_count` is a stored column | ✅ |
| Roster loads students in one `IN` query instead of one query per enrolment | `app/services/academic.py:1396-1401` — `Student.id.in_({e.student_id for e in enrollments})` | ✅ |
| Identity resolves user + roles + permissions in one statement | `app/auth/service.py:166-173` — `joinedload(User.roles).joinedload(Role.permissions)` | ✅ |

The identity change preserves the authorization result by construction: the same `Role` and
`Permission` objects are attached to the same `User`, so every downstream permission check
sees identical data. The roster change preserves the payload (the Phase 10 report records a
field-by-field comparison of 7 API rows against 7 database rows).

**Audit-history changes** (`app/audit/service.py`) are present and intact:

* `field_changes()` produces `{field: {"previous": ..., "new": ...}}` and includes only fields
  that actually differ; a field in one snapshot and not the other is a change to/from `None`.
* `sanitize_value()` normalises `UUID`, `date`/`datetime`/`time`, `Enum` and `Decimal` so a
  historical snapshot and a request payload compare equal.
* `sanitize_context()` recursively redacts keys matching a denylist (`password`, `token`,
  `secret`, `passport_number`, `visa_number`, `residence_permit_number`, `checksum`,
  `content`, `file_bytes`, …) and truncates long values to 200 characters.
* `record_audit` only *adds* to the caller's session and never commits, so an audit entry
  shares the transaction of the change it describes — a rolled-back change cannot leave a
  record claiming it happened.

**Not re-measured:** the throughput and latency figures in Phase 10 §D.4/§D.5 were not
re-run. The measurements exist on disk (`.perf/phase10_baseline.json` at 02:35,
`.perf/phase10_after.json` at 02:56, `.perf/phase10_profile.json`) and are correctly outside
the tracked tree. This report confirms the *code that produced them* is present; it does not
independently reproduce the numbers.

---

## 8. Previous engineering reports and evidence

All present and non-empty. `docs/` holds 32 entries.

| Document | Size |
|---|---|
| `v3-phase-8-completion-report.md` | 13,989 B |
| `v3-phase-10-stabilization-and-release-hardening-report.md` | 43,025 B |
| `v3-release-baseline.md` | 17,926 B |
| `v3-full-system-stability-and-institutional-readiness-report.md` | 51,521 B |
| `v3-change-impact-and-recovery-assessment.md` | 30,275 B |
| `engineering-assessment-v3-2026-11-24.md` | 51,972 B |
| `engineering-remediation-v3.md` | 28,055 B |
| `functional-certification-v3.md` | 31,610 B |
| `production-readiness-certification-v3.md` | 23,226 B |
| `final-presentation-readiness-v3.md` | 29,537 B |
| `deployment-v3.md` | 8,035 B |
| `migration-rehearsal-report.md` / `.json` | 1,268 B / 4,061 B |
| `v3-timetable-functional-completion-report.md` | 23,453 B |
| `v3-timetable-functional-comparison.md` | 48,674 B |
| `scu-timetable-implementation-plan.md` | 35,126 B |

Evidence: `docs/evidence/` contains **16 files** — 7 `timetable-comparison` items (including
the `api-evidence.md` transcript) and 8 `timetable-completion` screenshots — and they are
**tracked in Git**, committed in `c2f5c5b`. They therefore survive a fresh clone, which they
did not before that commit.

---

## 9. Timetable implementation and its uncommitted changes

Nothing was lost or overwritten.

* The timetable UI exists at `apps/web/src/app/[locale]/(protected)/app/timetable/page.tsx`
  (added in `c2f5c5b`).
* The API contract is intact — 5 timetable paths in `apps/web/openapi.json`:
  `/api/v1/academics/timetable`, `/api/v1/academics/timetable/{entry_id}`,
  `/api/v1/academics/timetable/reconciliation`,
  `/api/v1/academics/institutional-timetable`,
  `/api/v1/academics/students/{student_id}/timetable`.
* The backend suite module is present: `apps/api/tests/test_institutional_timetable.py`
  (added in `c2f5c5b`).
* Timetable-specific migrations remain in the chain: `a7b8c9d0e1f2_scu_timetable_reference`,
  `b3d5e7f9a1c2_university_calendar_days`, `c7d9e1f3a5b7_vacation_calendar_ranges`,
  `f3b7c2d9e6a1_late_enrollment_authorization` (the head).
* Phase 10 evidence for the timetable is committed and tracked (§8).

**The only working-tree change touching timetable code** is in
`apps/api/tests/test_institutional_timetable.py`, and it is lint-only: `TestClient` moved
behind `if TYPE_CHECKING:` to satisfy ruff. The full diff for that file is 6 lines of import
reorganisation and contains **no test logic change, no assertion change and no skipped or
removed test**.

Consequently the "uncommitted timetable work" referred to in the brief is no longer
uncommitted: it *is* `c2f5c5b`, and it is pushed to `origin/main`. What remains uncommitted is
the CI/CD work described in §10.

---

## 10. CI/CD modifications: security, permissions and tests

The working tree holds 16 entries: 12 modified, 4 untracked, **0 staged**.

```
 M .github/workflows/ci.yml                       ?? .github/dependabot.yml
 M Makefile                                       ?? .github/workflows/release.yml
 M apps/api/app/audit/service.py                  ?? apps/web/scripts/check-locale-routes.mjs
 M apps/api/app/routers/academic.py               ?? docs/v3-ci-cd-setup-and-release-workflow.md
 M apps/api/app/services/academic.py
 M apps/api/tests/test_audit_history.py
 M apps/api/tests/test_audit_immutability.py
 M apps/api/tests/test_institutional_timetable.py
 M apps/api/tools/seed_load.py
 M apps/web/openapi.json
 M apps/web/package.json
 M apps/web/pnpm-workspace.yaml
```

### 10.1 The six Python edits are cosmetic — with one assertion to justify

| File | Change | Behavioural effect |
|---|---|---|
| `app/audit/service.py` | three nested `if`s merged into one | none — same condition, same short-circuit order |
| `app/routers/academic.py` | two schema imports reordered | none |
| `app/services/academic.py` | two schema imports reordered | none |
| `tools/seed_load.py` | housing import block moved into alphabetical position | none |
| `tests/test_audit_history.py` | one blank line removed | none |
| `tests/test_institutional_timetable.py` | `TestClient` moved under `TYPE_CHECKING` | none |

One edit needs to be called out because it touches a security test:

```diff
-    assert EXPECTED_TRIGGERS <= installed
+    assert installed >= EXPECTED_TRIGGERS
```

This is the **same assertion**. `A <= B` and `B >= A` are identical for sets, both meaning
"the installed trigger names contain every expected trigger name". It is a ruff
`SIM300`-style yoda-condition fix, not a relaxation: the assertion still requires all three
triggers by name, and it still permits additional triggers. No test was deleted, skipped,
marked `xfail`, or given a looser matcher anywhere in the diff.

### 10.2 `ci.yml` is hardening only

Comparing the committed workflow to the working-tree version:

**Added, and strictly stronger:**

* `changes` job — decides whether the browser suite is needed; on a missing/unusable base
  commit it **defaults to running every gate** (`code=true`) rather than skipping.
* `security` job — a "no real environment file is tracked" gate and `pnpm audit --prod
  --audit-level critical`.
* `persist-credentials: false` on *every* checkout (7 occurrences) — the token is no longer
  left in `.git/config`.
* Every action moved from a floating tag (`@v4`, `@v5`) to an exact 40-character commit.
* `pnpm check:locales` — serves the production build and asserts HTTP 200, `<html lang>` and
  `dir=rtl` for all five locales. A new gate, not a replacement.
* Image inspection scoped deliberately to `/app` and excluding `node_modules`, with the
  rationale recorded (a whole-filesystem `*.pem` scan flags `/etc/ssl/cert.pem` and could
  never pass).

**Weakened:** nothing. There is no new `continue-on-error` on a correctness gate — the two
present are the Python and the full frontend **advisory reports**, and the *blocking* frontend
gate (`--audit-level critical`) sits in front of the advisory one. `|| true` appears exactly
twice, both on a `grep` whose emptiness is then tested explicitly. No `set +e`, no
`--no-verify`, and no test command was removed.

**Job set:** the committed workflow had 4 jobs (`backend`, `contract`, `frontend`, `images`);
the working tree has 7 (`changes`, `backend`, `contract`, `frontend`, `images`, `security`,
`e2e`). The `e2e` job existed before and still exists; it is now gated on `changes` so a
documentation-only change does not spend 45 minutes on Chromium.

---

## Additional CI/CD review

### A. Action pins resolve to real releases

Eight distinct action references, all `owner/repo@<40 hex>`. Each was resolved against the
upstream repository with `git ls-remote`, which returns the *actual* ref names:

| Action | Pinned SHA | Upstream ref confirmed |
|---|---|---|
| `actions/checkout` | `3d3c42e5aac5ba805825da76410c181273ba90b1` | `refs/tags/v7.0.1` |
| `actions/setup-node` | `949feb2413d6458794dcd2491c4babbbce0c15c1` | `refs/tags/v7.1.0` |
| `actions/setup-python` | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | `refs/tags/v7.1.0` |
| `actions/upload-artifact` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | `refs/tags/v7.0.2` |
| `pnpm/action-setup` | `73e46992e05b19abd31f2f3c20e0e7370d762115` | `refs/tags/v6.1.1^{}` (peeled) |
| `docker/setup-buildx-action` | `f87e5991a6d7451dcb8d9637bfbc97413f497069` | `refs/tags/v4.4.1` |
| `docker/build-push-action` | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` | `refs/tags/v7.4.0` |
| `docker/login-action` | `8aa5831fb8d48d8f76594c7ddde61ae58019f550` | `refs/tags/v4.8.0` |

Every SHA is the commit the named tag points at, so the inline `# vX.Y.Z` comments are
accurate and none of them resolves to an unrelated or moving ref. `pnpm/action-setup` required
the peeled (`^{}`) ref because it uses annotated tags; the commit, not the tag object, is what
is pinned.

No `pull_request_target`, no `workflow_run`, no `issue_comment` trigger anywhere — so no
workflow runs with a write token on code from an untrusted fork.

### B. YAML and triggers

All six files parse cleanly: `ci.yml`, `release.yml`, `dependabot.yml`,
`apps/web/pnpm-workspace.yaml`, `docker-compose.prod.yml`, `docker-compose.perf.yml`. (Note
for future tooling: a YAML 1.1 loader reads the bare key `on` as boolean `true`; GitHub's
parser does not, so this is a tooling quirk, not a defect.)

| Workflow | Triggers |
|---|---|
| `ci.yml` | `push` → `branches: [main]`; `pull_request` (all branches); `workflow_dispatch` |
| `release.yml` | `push` → `tags: ["v*"]`; `workflow_dispatch` with `version`, `environment` (staging/production), `rollback_to`, `run_migrations` (default `false`) |

Top-level permissions are `contents: read` in **both** workflows; the only elevated
permission is granted per job, below.

`concurrency`: CI uses `ci-${{ github.ref }}` with `cancel-in-progress: true` (superseded
pushes are cancelled safely), while release uses `release-<env>` with
`cancel-in-progress: false` — a release in flight is never killed.

### C. Job dependencies

```
ci:      changes ──> e2e
         backend, contract, frontend, images, security   (independent)

release: build ──> migrate ──> deploy
         build ──> release   (tag pushes only)
```

`e2e` is the only CI job with a dependency, and it depends on the cheap `changes` job rather
than on the expensive ones — so a backend failure does not mask a browser failure, and CI
wall-clock is not the sum of its jobs. Both `migrate` and `deploy` require `build`,
guaranteeing an image exists before anything is released.

### D. Required status-check names

If branch protection is enabled, the check names must match these job `name:` values exactly:

1. `Detect code changes`
2. `Backend (tests, lint, migrations)`
3. `API contract (OpenAPI current)`
4. `Frontend (types, i18n, build, locales)`
5. `Docker images and production composition`
6. `Security (advisories)`
7. `Browser E2E (isolated stack)`

Recommended: require 1–6 unconditionally. For 7, note that it is skipped for
documentation-only changes; because `e2e` always exists in the run (it `needs` `changes`), the
check is always *reported* and never stays in "Expected" limbo, and GitHub treats a skipped
job as satisfying a required check. Confirm that rendering on the first pull request before
making it required — this is a repository setting, and this report does not change repository
settings.

### E. Release artifacts and GHCR permissions

| Job | `permissions` | Justification |
|---|---|---|
| `build` | `contents: read`, **`packages: write`** | pushes images to GHCR |
| `migrate` | `contents: read`, `packages: read` | pulls the image, runs Alembic over SSH |
| `deploy` | `contents: read`, `packages: read` | pulls and rolls the stack |
| `release` | **`contents: write`** | creates the GitHub Release |

Nothing holds `write` that does not need it, and no job holds `id-token`, `actions` or
`security-events`.

Registry path `ghcr.io/ezra5566/sycumain_v3-api` / `-web` is lower-case — required, since the
repository name `SYCUMAIN_V3` is not, and GHCR rejects upper-case paths.

Each image is published with **two immutable tags**: the semver version and the 12-character
commit. Version input is validated against `[0-9]*.[0-9]*.[0-9]*` and the job exits non-zero
otherwise. OCI labels record source, revision and version.

The release artifact is `release-manifest.json` (version, commit, `built_at`, and each image's
repository, tag and **registry digest**), uploaded with 90-day retention, downloaded in the
`release` job with the preinstalled `gh run download` (no extra third-party action), and
attached to the GitHub Release via `gh release create --notes-file -`. That manifest is what a
rollback and an audit both read.

### F. Deployment jobs are disabled without explicit configuration

Both host-touching jobs carry two independent conditions:

```yaml
environment: ${{ inputs.environment }}
if: ... && vars.DEPLOY_ENABLED == 'true'
```

`build` and `release` run on a tag push, but **neither `migrate` nor `deploy` can**: both also
require `github.event_name == 'workflow_dispatch'`. So a `v*` tag publishes images and a
release manifest and stops. Until an operator creates the `staging`/`production` environments,
sets `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY`, and flips the `DEPLOY_ENABLED`
repository variable, the deployment jobs are **skipped** — visibly, never silently
"successful". `migrate` additionally requires `run_migrations == true`, which defaults to
false.

### G. Rollback behaviour — and the database recovery it does not perform

Rollback is "re-run the workflow with `rollback_to` set to a previously published version".
Mechanically it works: `build` is skipped (`inputs.rollback_to == ''` is false), `migrate` is
skipped (it requires `rollback_to == ''`), `deploy` resolves the named tag, authenticates to
GHCR, `docker compose pull`, `up -d`, then polls `$APP_ORIGIN/ready`.

**The important limitation:** rollback restores *images only*. It never touches the database.
That is deliberate and correct for a forward-only schema, but it means:

* rolling back to a version whose code expects an **older** schema than the database has is
  not made safe by anything in the workflow — the container will start and then fail on the
  first query that touches a changed table;
* no backup is taken before `migrate` runs, and the workflow does not verify one exists;
* `scripts/restore.sh` exists and is the right tool (verify mode restores into
  `school_portal_restore_verify` and checks schema, row counts, document bytes and SHA-256
  checksums; `--live` requires typing the database name), but **it is not invoked by
  `release.yml`**, and the operator is not prompted to take a backup.

So the answer to "does rollback accidentally skip necessary database recovery considerations?"
is: it skips database recovery *by design and by omission*. Design-wise, forward-only is the
right policy and is documented. Omission-wise, nothing in the workflow records the schema
revision each version expects, and nothing forces a verified backup before a migration. That
is a documentation/process gap, listed as correction **C2**.

### H. The six frontend dependency advisories

`pnpm audit --prod` at HEAD, unmodified lockfile:

| # | Package | Severity | Advisory | Installed | Patched | Path |
|---|---|---|---|---|---|---|
| 1 | `postcss` | **high** | Arbitrary file read / information disclosure via attacker-controlled `sourceMappingURL` in CSS comments | 8.4.31 | `>=8.5.12` | `. > next > postcss` |
| 2 | `postcss` | **high** | Path traversal in previous-source-map auto-loading leads to arbitrary `.map` disclosure | 8.4.31 | `>=8.5.18` | `. > next > postcss` |
| 3 | `source-map-js` | **high** | Event-loop denial of service via indexed source-map section offsets | 1.2.1 | `>=1.2.2` | `. > tailwindcss-animate > tailwindcss > postcss > source-map-js` |
| 4 | `postcss` | moderate | XSS via unescaped `</style>` in stringify output | 8.4.31 | `>=8.5.10` | `. > next > postcss` |
| 5 | `postcss` | moderate | Incomplete fix of GHSA-6g55-p6wh-862q — `sourceMappingURL` reads arbitrary `.map` files when `from` is unset | 8.4.31 | `>=8.5.23` | `. > next > postcss` |
| 6 | `postcss-selector-parser` | moderate | Quadratic complexity in flat selector parsing allows CPU exhaustion | 6.1.4 | `>=6.1.5` | `. > tailwindcss-animate > tailwindcss > postcss-selector-parser` |

Totals: **3 high, 3 moderate, 0 critical** — which is why `pnpm audit --prod --audit-level
critical` passes while the full report is `.continue-on-error: true`.

Assessment, stated plainly:

* All three `postcss` (4, 5, 1, 2) and one `postcss-selector-parser` finding are **build-time**
  transitive dependencies of `next` and `tailwindcss`. `postcss` processes CSS at build time;
  it does not parse untrusted user input at runtime. Their real exposure is a malicious CSS
  file in the build context, not an attacker over HTTP.
* `source-map-js` 1.2.1 (finding 3) is reachable at build time through `tailwindcss-animate`;
  the same reasoning applies.
* None of the six is critical, none is a runtime authentication, injection or deserialisation
  issue, and the only way to clear them is a coordinated bump of `next` (which pins `postcss`)
  and `tailwindcss-animate`. That is a framework upgrade with its own regression surface, which
  is why it is proposed by Dependabot rather than forced through the security gate.
* The blocking gate is not removed: `--audit-level critical` still fails the build on any
  critical advisory.

### I. Supported Node LTS upgrade path

**Finding: the pipeline and the web image both run Node 20, which reached end of life on
2026-04-30 and has received no security release since.** `ci.yml` sets
`NODE_VERSION: "20"` and `infra/docker/Dockerfile.web` builds `FROM node:20-alpine`.

Current support status (nodejs.org release schedule, as of November 2026):

| Line | Status | End of life |
|---|---|---|
| 26 (Lithium) | **Active LTS** (since 2026-10-28) | 2029-04-30 |
| 24 (Krypton) | Maintenance LTS (since 2026-10-20) | 2028-04-30 |
| 22 (Jod) | Maintenance LTS | 2027-04-30 |
| 20 (Iron) | **End of life** | 2026-04-30 |

Recommended path — **Node 24 LTS now, Node 26 as the follow-up**:

1. `24` is the conservative target: it is the version GitHub Actions already defaults to, it
   is supported until April 2028, and the ecosystem (Next 15, pnpm 12, Playwright) runs on it
   without changes. Node 26 buys one more year but is nine months younger in ecosystem
   adoption; take it deliberately, not as the first move.
2. Do **not** stop at 22 — it expires in five months and would force a second upgrade almost
   immediately.
3. Concrete edits (all three must move together):
   * `ci.yml`: `env.NODE_VERSION: "24"`.
   * `infra/docker/Dockerfile.web`: `FROM node:24-alpine AS base`.
   * `apps/web/package.json`: add `"engines": { "node": ">=24" }` (currently absent — nothing
     prevents a developer or a runner from using an EOL runtime today).
4. Optional but recommended: add `apps/web/.nvmrc` containing `24`, so the local and CI
   versions cannot drift.
5. Re-run the affected gates after the bump: `pnpm install --frozen-lockfile`, `pnpm
   typecheck`, `pnpm lint`, `pnpm i18n:check`, `pnpm build`, `pnpm check:locales`, plus the
   Playwright suite — native modules (`@swc/core`, `@parcel/watcher`, `sharp`) are rebuilt per
   Node ABI, which is exactly what `allowBuilds` in `pnpm-workspace.yaml` authorises.
6. This is a **separate change from the CI work being pushed**. It changes a runtime and
   therefore needs its own verification; folding it into this push would mean the first green
   run tells you nothing about which of the two caused a failure.

### J. Exact commands to execute the browser E2E suite

The suite runs against its own disposable stack — database `school_portal_e2e`, project
`school-portal-v3-e2e`, ports 5436 / 8002 / 3002 — so it can run while the development stack
on 5435 / 8001 / 3101 is up. `scripts/e2e.sh` refuses to run if the resolved composition
references `school_portal_v2` or `school_portal_v3`, and tears the stack down with
`down -v` on success, failure or interrupt.

```bash
# 0. Prerequisites: a running Docker daemon, and the web dependencies installed.
cd SYCUMAIN_V2
docker info >/dev/null

# 1. Frontend dependencies from the lockfile (required — the suite runs from apps/web).
cd apps/web
pnpm install --frozen-lockfile

# 2. Chromium for Playwright (once per machine; CI does this every run).
pnpm exec playwright install --with-deps chromium

# 3. Run the whole suite against the isolated stack.
cd ../..
./scripts/e2e.sh
```

Equivalent and more specific invocations:

```bash
make e2e                                            # same as ./scripts/e2e.sh
./scripts/e2e.sh e2e/smoke.spec.ts                  # one spec, args forwarded to Playwright
./scripts/e2e.sh e2e/accessibility.spec.ts          # a single named suite
```

What the script supplies, and therefore what is *not* needed on the command line:

| Variable | Value set by `scripts/e2e.sh` |
|---|---|
| `E2E_BASE_URL` | `http://localhost:3002` |
| `E2E_API_URL` | `http://localhost:8002` |
| `E2E_PASSWORD` | `${E2E_PASSWORD:-password123}` (override by exporting it) |

It also waits on `http://localhost:8002/ready` and `http://localhost:3002/en/login` before
starting Playwright (readiness polling, never a fixed sleep), and writes
`apps/web/test-results/` plus, on failure, `apps/web/test-results/docker-failure.log`.

Note: `cd apps/web && pnpm test:e2e` (`playwright test`) is **not** standalone — it assumes a
running stack and the `E2E_*` variables, which is why `scripts/e2e.sh` is the supported entry
point and what CI calls.

The CI job does exactly steps 1–3 above, preceded by
`pnpm exec playwright install --with-deps chromium`, and uploads `playwright-report/` and
`test-results/` as `playwright-diagnostics` (7-day retention) with `if: always()`.

---

## Corrections required before push

### C1 — CI and the web image run an EOL Node.js (security)

`ci.yml` pins `NODE_VERSION: "20"` and `infra/docker/Dockerfile.web` uses `node:20-alpine`.
Node 20 ended support on 2026-04-30. Bump to 24 (§I) as a **separate, separately verified
change**, or accept in writing that the first release ships on an unsupported runtime.
`package.json` also has no `engines` field, so nothing currently prevents an EOL runtime
locally.

### C2 — Rollback has no database-recovery guard (§G)

`rollback_to` redeploys an older image and deliberately runs no migration, but nothing records
the schema revision a version expects and nothing forces a verified backup before `migrate`.
Minimum fix, documentation-level: state in `docs/deployment-v3.md` and in the `release.yml`
header that (a) `migrate` must be preceded by `scripts/backup.sh` and a `scripts/restore.sh
latest` verification, and (b) `rollback_to` is only valid for a version whose expected schema
revision matches the database's current `alembic_version`. Recording the revision in
`release-manifest.json` would make that check mechanical.

### C3 — Phase 10 §B.2 wording overstates what the `REVOKE` does (§4.2)

The `REVOKE ... FROM PUBLIC` does not remove the owning role's `UPDATE`/`DELETE`/`TRUNCATE`;
the trigger is the effective control. The Phase 10 report should say so explicitly, because as
written a reader could test grants on the owner, see them still present, and conclude the
control is broken.

### C4 — Operational: the default local database is 5 revisions behind head (§4.4)

`DATABASE_URL` unset resolves to `localhost:5434/school_portal_v2`, which is at
`a7c1e9b25d40` and has **no** audit triggers. Before quoting any local verification of audit
immutability, run `cd apps/api && python -m alembic upgrade head` against the intended
database, or point `DATABASE_URL` at the database at `f3b7c2d9e6a1`. This is database state,
not a repository defect, and no database was migrated during this verification.

### Not corrections — recording them so they are not rediscovered as surprises

* `alembic upgrade head --sql` fails at `9a1f2b3c4d5e` (offline mode cannot read rows).
  Pre-existing, online-only is the supported path.
* `test_audit_immutability.py`'s assertion operator reversal is semantically identical (§10.1).
* `continue-on-error: true` on the two advisory reports is deliberate and documented; the
  blocking critical-advisory gate is present and separate.

---

## What this verification did not do

Stated so the conclusion is not read as broader than the evidence:

* **No benchmark was re-run.** Phase 10's throughput and latency figures were not reproduced;
  only the code that produced them was confirmed present (§7).
* **No live ClamAV scan was performed.** §6 verifies the Compose service, healthcheck,
  dependency wiring, forwarded variables and the fail-closed scanner implementation; it does
  not re-run the EICAR/known-good probe that Phase 10 §F.3 records.
* **`scripts/provision-db-roles.sh` was not executed.** Role creation is a deployment action.
  Its guards and grants were verified by reading it, and the production Compose wiring that
  depends on it was verified by reading that.
* **No workflow was run on GitHub.** Every statement about CI/CD behaviour is static
  verification: YAML parsed, action SHAs resolved against upstream with `git ls-remote`, job
  graph and conditions read, permissions enumerated. The only executed evidence is local —
  the migration chain, the trigger rejections, and the 26 tests.
* **No repository setting was read or changed.** Branch protection, rulesets, environments,
  `DEPLOY_ENABLED` and Dependabot security updates remain as they were; §D and §F describe what
  would need to be configured, not what is configured.
* **Nothing was pushed, committed, staged, deployed or reset.** `git diff --cached` is empty;
  working tree 16 entries before this report, 17 after it (this file is untracked). V1 was not
  contacted for writing, and no V1 file, container or schema was modified.

---

## Conclusion

The two reported states reconcile completely: `8467300` is the direct parent of `c2f5c5b`, and
`c2f5c5b` committed the Phase 10 tree rather than replacing it — 81 additions, 73
modifications, **zero deletions**. Every Phase 10 artifact is present, the audit trigger
rejects `UPDATE`/`DELETE`/`TRUNCATE` even for a PostgreSQL superuser, the migration chain
applies from empty to a single head with model/migration parity, the fail-closed guards refuse
V1 and unconfirmed production targets, all reports and evidence are tracked in Git, and the
timetable implementation is intact with no logic change in the working tree. The CI/CD
additions harden the pipeline and weaken nothing.

What stands between this tree and a push is not baseline integrity but three specific,
bounded items: an end-of-life Node runtime in CI and the web image (C1), a rollback path with
no database-recovery guard (C2), and two documentation imprecisions (C3, C4). None requires
touching Phase 10 code, rewriting history, or discarding work.

**SAFE AFTER SPECIFIC CORRECTIONS** — apply C1–C4 (C1 as its own verified change, C2–C3 as
documentation edits, C4 as an operational step), then push.
