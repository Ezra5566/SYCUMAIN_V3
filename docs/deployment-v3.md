# Deploying SYCUMAIN V3

**Status:** written during the remediation of 2026-11-24. Everything here was
executed locally against synthetic data; nothing has been deployed to a real
host, and no institutional record has been migrated.

---

## 1. Two stacks, two files

| Purpose | File | Web | API | Database |
|---|---|---|---|---|
| Development | `docker-compose.yml` | 3101 | 8001 | 5435 |
| Production-shaped | `docker-compose.prod.yml` | internal only | internal only | internal only, TLS at the edge |
| Browser tests | `docker-compose.test.yml` | 3002 | 8002 | 5436 |

They are separate files, not overrides. The development stack publishes the
database and bind-mounts source; merging the two would let a development change
silently weaken production. The browser-test stack is disposable and is deleted
by `scripts/e2e.sh` on every run.

The PostgreSQL instance on **5434** is the test database used by the pytest
fixture (`apps/api/tests/conftest.py`). It holds no application data: the
fixture creates and drops its schema. The suite refuses to run against a URL
that is not `localhost/school_portal_test*`.

---

## 2. Topology

```
Browser ──HTTPS──► Caddy :443 ──► web (Next.js standalone) :3000
                        └────────► api (FastAPI/uvicorn)  :8001
                                        │
                                        └──► postgres :5432
```

One public origin. `/api/*`, `/health`, `/ready` and the docs go to the API;
everything else to Next.js. Consequences that matter:

* the session cookie is same-origin, so no CORS exception is needed;
* the cookie can be `Secure`, because the browser's origin is HTTPS;
* the API is never published, so it cannot be reached except through Caddy;
* `NEXT_PUBLIC_API_URL` is the public origin, because the **browser** calls it;
* `API_INTERNAL_URL` is `http://api:8001`, because **server rendering** calls
  the API inside the network.

`infra/caddy/Caddyfile` obtains a real certificate by ACME.
`infra/caddy/Caddyfile.local` uses Caddy's local CA for a ring-fenced rehearsal
host. There is no other TLS arrangement in this repository; a different edge
(nginx, an institutional load balancer) must reproduce the same routing rules
and forwarded headers.

---

## 3. Release procedure

```bash
cp .env.production.example .env.production      # fill in every REPLACE_ME
docker compose --env-file .env.production -f docker-compose.prod.yml build
make backup                                     # dump + documents + digests
make restore-verify                             # prove the dump restores
cd apps/api && python3 tools/schema_revision.py  # revision this code expects
docker compose --env-file .env.production -f docker-compose.prod.yml \
  --profile tools run --rm migrate              # explicit schema step
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

Migrations **never** run when a container starts: `api` is started with
`uvicorn` only, and `migrate` sits behind the `tools` profile. A failed
migration therefore stops the release before any container is replaced, rather
than half-applying a schema on boot.

**A backup and a verified restore are prerequisites for the migration step, not
optional hygiene.** A forward migration is the one action that can turn a later
image rollback into a broken deployment, because it changes the schema under
code that expects the older one. `release.yml`'s `migrate` job therefore
requires the operator to tick `backup_verified` (which attests to `make backup`
and `make restore-verify` succeeding for this release) and fails without it.
When releasing by hand, run the same two commands before `migrate`.

### First administrator

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml \
  run --rm api python -m app.cli bootstrap-admin --email registrar@example.edu
```

The temporary password is printed **once** and must be changed at first
sign-in. The API must have started at least once before this command: roles and
permissions are reconciled during application startup, so `bootstrap-admin` on
a brand-new database reports `Unknown role(s): ADMIN`. That ordering is a
usability wrinkle, not a defect — start the stack, then bootstrap.

### Verification after a release

```bash
curl -fsS https://<host>/health          # process is alive
curl -fsS https://<host>/ready           # database + storage are usable
curl -fsS -o /dev/null -w '%{http_code}\n' https://<host>/en/login
```

`/ready` is the only health check that proves the instance can serve records.

---

## 4. Secrets

All production values come from the environment (`--env-file`). Nothing is
hardcoded, and `.env*` files are excluded from every image build context —
`apps/api/.env` was previously copied into the API image and read by
pydantic-settings for every container, which is why a production start failed
with development values (`DEBUG`, `PASSWORD_RESET_DELIVERY=dev`,
`MALWARE_SCANNER=dev-clean`).

The application refuses to start in production when:

* `SECRET_KEY` is weak or shorter than 32 characters;
* `DATABASE_URL` uses the documented `portal:portal` credentials;
* `DEBUG` is true, or `SEED_DEMO_DATA` is on;
* `PASSWORD_RESET_DELIVERY=dev`, or `ACTIVATION_RETURN_LINK` is true;
* `MALWARE_SCANNER` is `dev-clean`/`eicar-test`;
* `CORS_ORIGINS` is empty or contains a non-HTTPS origin;
* `SESSION_COOKIE_SECURE` is false.

Generate `SECRET_KEY` and `POSTGRES_PASSWORD` with `openssl rand -hex 32`. Keep
`.env.production` out of version control (it is git-ignored).

---

## 5. Uploads and malware scanning

`MALWARE_SCANNER=disabled` **fails closed**: uploads are refused rather than
stored unscanned. Student document upload therefore requires either a ClamAV
instance reachable at `CLAMAV_HOST:CLAMAV_PORT` with `MALWARE_SCANNER=clamav`,
or an institutional decision to run without scanning. This is an external
dependency that this repository does not provision.

Documents are stored on the `documents` named volume (`/app/var/storage`) by
default, or in S3-compatible storage when `STORAGE_BACKEND=s3` and the
`STORAGE_S3_*` variables are set.

---

## 6. Backup and restore

```bash
make backup           # pg_dump (custom format) + document archive + SHA-256 manifest
make restore-verify   # restores into a scratch database and checks it
```

`scripts/backup.sh` writes to `./backups` on the host, never into the database
volume, and refuses to finish unless the dump is a readable PostgreSQL archive.
It also archives the document volume and records a digest for every artifact.

`scripts/restore.sh` in its default (verify) mode restores into
`school_portal_restore_verify`, then checks:

* the schema restores and `alembic_version` is present;
* table, student and user counts are reported;
* every `documents.object_key` exists in the restored bytes;
* every `documents.checksum_sha256` matches the restored file.

`--live` replaces the live database (and with `--with-storage`, the document
store) and requires typing the database name. It stops the API first, because
an open connection blocks a restore.

**Measured on a disposable stack (2026-11-24):** backup produced a 247 KB dump
and a 191-entry document archive; verification restored 63 tables with 1 user
and 0 documents and reported `missing objects: 0`, `checksum failures: 0`.
There is no automated nightly schedule in this repository; scheduling
`make backup` is an operator responsibility until one is added.

---

## 7. What is deliberately not automated

These are external dependencies, not code defects:

| Item | Consequence |
|---|---|
| Email delivery for password reset | `PASSWORD_RESET_DELIVERY=disabled` hides the flow. There is no mail provider integration. |
| ClamAV | Uploads refused while the scanner is `disabled` (fail-closed). |
| Nightly backups / off-host retention | `make backup` is manual; retention and off-site copies are an operator policy. |
| Monitoring and error reporting | JSON logs and `/ready` only. No APM, no alerting. |
| Load-tested capacity | No numbers are claimed. See §9 of `engineering-remediation-v3.md`. |
| Institutional data migration | Tooling exists; the canonical database is not yet chosen. |

---

## 8. Rolling back

A rollback moves images and nothing else. It never runs `alembic`, never
restores a database, and never rewrites data — so the schema must already be
compatible with the version being restored.

0. **Check the schema revision first.** `release-manifest.json` records
   `schema_expected_head`, the revision the released code was built against,
   and `apps/api/tools/schema_revision.py` prints the revision of the tree you
   are deploying. Compare it with the database's actual revision:

   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml \
     --profile tools run --rm migrate python -m alembic current
   ```

   A rollback is valid only when the target version's `schema_expected_head`
   equals that value. If the database is **ahead**, the older code will start
   and then fail on the first query that touches a changed table — in that case
   take option 2, not option 1.
1. Redeploy the previous image tags (nothing in the release writes
   destructively to the schema by itself).
2. If the release included a migration, prefer a **new forward revision**;
   `alembic downgrade` exists for every revision but is refused by several of
   them while institutional rows exist (`immigration_reminders`, examinations),
   by design.
3. `scripts/restore.sh --live` is the last resort, not the first. It requires
   typing the database name and stops the API, because a live restore replaces
   rows rather than reinterpreting them.

Every migration in this repository documents its own downgrade position in the
module docstring.
