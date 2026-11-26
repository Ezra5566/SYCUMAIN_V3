# V3 — Prioritised next-development roadmap

**Basis:** the Phase 8 assessment and certification, plus a fresh inventory of what is
actually implemented. Date: 2026-11-25.

## How this list was chosen

The platform's modules are complete: every backend router has a frontend surface, no
navigation entry is marked "coming soon", and there is no `TODO`, `FIXME` or
`NotImplemented` in shipped application code. So this roadmap does **not** propose new
features to make the platform look finished. It is built from four kinds of evidence:

1. gaps found during Phase 8 verification (host migration target, scanner endpoint);
2. the deliberate rollout controls in the code (admission phase gates, retention
   values, email channel) that someone must now decide;
3. what is certified versus assumed (browser coverage, backup/restore, real data);
4. the difference between "the build passes" and "an institution can run it".

Under the brief's strict definition — blocking functionality or data-integrity defects
— **P0 is empty**. The P0 rows below are production-adoption blockers: they block
going live with real data, not the next sprint.

---

## P0 — blocking for production / real data

| # | Item | Why it blocks | Migration impact |
|---|---|---|---|
| P0-1 | **Real-data migration rehearsal with rollback.** Load a copy of institutional data into an isolated stack, run the V1→V3 import and identity reconciliation, then roll back and re-run. | The reconciliation paths (`IDENTITY_MISMATCH`, `AMBIGUOUS_IDENTITY`, `EXISTING_STUDENT_MATCHED`) exist and are tested on synthetic data only. Nobody knows the real conflict rate or whether rollback restores the source. | None (rehearsal only). Any schema change it reveals comes back as a separate proposal. |
| P0-2 | **Retention policy values.** Have the institution approve `RETENTION_*` for graduated, withdrawn, inactive, documents, audit. | `retention-report` currently answers "policy pending approval", so nobody can say what may be deleted or archived — and nothing may be. | None (configuration). |
| P0-3 | **Malware scanning endpoint for production.** Decide: external ClamAV endpoint, or add a `clamav` service to `docker-compose.prod.yml`. | Today `CLAMAV_HOST=clamav` points at a service the production composition does not define, and `MALWARE_SCANNER=disabled` fails closed — so document upload does not work in production. | None. |
| P0-4 | **Production-shaped rehearsal.** Bring up `docker-compose.prod.yml` with Caddy and a real certificate: HTTPS origin, `CORS_ORIGINS` containing only that origin, secure session cookie, production image, both API and web behind the proxy. | The composition validates, and the image was built and served in isolation, but the combination has never run end to end. Secure-cookie and origin behaviour are exactly what changes in production. | None. |

---

## P1 — essential institutional workflows and safety

| # | Item | Why it matters now |
|---|---|---|
| P1-1 | **UAT account provisioning runbook.** Replace the shared demonstration password with named UAT accounts created through the admin-assisted flow, one per role and per office, with a documented rotation. | The demo credential is correct for a demo and wrong for an institution. The mechanism already exists; it needs a written procedure and one rehearsal. |
| P1-2 | **Decide the admission phase gates for UAT.** `ADMISSIONS_WRITE_ENABLED`, `ADMISSION_MIGRATION_CONSOLE_ENABLED`, `ADMISSION_CHANGE_REQUESTS_ENABLED`, `ADMISSION_DATE_CORRECTION_ENABLED`, `ADMISSION_CORRECTIONS_ENABLED` are all `false` in `.env.example` and `true` in the development compose. | Which workflows UAT is expected to test determines which gates are open. Today that is an accident of which compose file is used. |
| P1-3 | **Fail-closed guard in `alembic/env.py`.** Refuse any database whose name is not `school_portal_v2` / `school_portal_test*`, mirroring the guard already in `tests/conftest.py`. | `alembic upgrade` from the host virtualenv currently targets a different database than the V3 stack, and the fallback default is V1's `localhost:5433`. A one-line mistake could migrate the reference installation. |
| P1-4 | **Backup → restore rehearsal.** Run `scripts/backup.sh`, restore into a scratch stack, verify the SHA-256 manifest and row counts. | A backup that has never been restored is a hope, not a control. The scripts exist; the proof does not. |

---

## P2 — important operational improvements

| # | Item | Note |
|---|---|---|
| P2-1 | **SMTP relay for notification mail**, if the institution wants expiry/support notifications or optional self-service reset. | `EMAIL_NOTIFICATIONS_ENABLED=false` and no relay is configured; the outbox already records what would be sent. Admin-assisted recovery does not depend on it. |
| P2-2 | **Full cross-browser certification.** WebKit across the whole suite; Firefox on a host where it launches. | Chromium is certified end to end. WebKit has a 27-test authentication subset; Firefox cannot run on this machine. |
| P2-3 | **Separate the demo and V1 stacks' resource budget**, or move the demo to production images. | Every "random failure" this phase traced back to Next's dev compiler under 3.8 GiB, including two soak aborts. The production image is a third of that pressure. |
| P2-4 | **Scheduled reminders / retention jobs** run by an external scheduler instead of API startup. | Reminders reconcile on startup today, which is idempotent but means a long-running process must be restarted to pick up a calendar change. |

---

## P3 — optional refinements

| # | Item |
|---|---|
| P3-1 | Give dormitory attendance and absence recording their own entry points if operators ask; both are currently panels inside `/app/attendance`. |
| P3-2 | Replace the remaining "coming soon" support in `navigation.ts` with a clean removal now that no entry uses it. |
| P3-3 | Document the demo-credential variable in the operator runbook next to the deployment guide. |

---

## Proposed implementation phases

Grouped so each phase has a demonstrable exit condition. **No phase proposes a schema
change or an architectural rewrite.**

### Phase 9 — "It runs where it will be operated" (1–2 days)
P0-4, P1-3, P1-4, P2-3.
*Exit:* the production composition runs behind HTTPS with a secure cookie; the host
alembic command refuses a foreign database; a backup restores byte-identically into a
scratch stack.

### Phase 10 — "The institution decides" (institutional input, then 1 day)
P0-2, P0-3, P1-1, P1-2, P2-1.
*Exit:* retention values approved and recorded; a working scanner endpoint; named UAT
accounts issued; the gate configuration for UAT written down and applied; an SMTP
decision made either way.

### Phase 11 — "Real data, reversible" (2–3 days)
P0-1.
*Exit:* a copy of institutional data imported, conflicts reconciled through the
existing workflows, results documented, rollback executed and re-import verified.

### Phase 12 — "Certified everywhere we claim" (1–2 days, partly host-dependent)
P2-2, P3-1…P3-3.
*Exit:* WebKit suite green, Firefox certified on a capable host, roadmap and runbook
documentation current.

---

## Explicit non-goals

- No rewrite of the admission, housing, immigration or examination modules — they are
  certified and unchanged in this phase.
- No new institutional features invented to fill the roadmap.
- No schema change until one of the P0 rehearsals produces a concrete requirement,
  presented with its migration and rollback plan.
- No weakening of authentication, permission or origin enforcement to make a
  rehearsal pass.
