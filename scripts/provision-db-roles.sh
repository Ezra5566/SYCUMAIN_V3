#!/usr/bin/env bash
#
# Provision the application database role for a production-shaped deployment.
#
#   POSTGRES_APP_USER=sycumain_app \
#   POSTGRES_APP_PASSWORD='...' \
#   docker compose --env-file .env.production -f docker-compose.prod.yml \
#     --profile tools run --rm provision-roles
#
# What this changes and why
# -------------------------
# The PostgreSQL image makes POSTGRES_USER a **superuser**, and every service in
# this project used to connect as that account. A superuser bypasses every
# GRANT: it can rewrite audit history, drop a table, or read every row, so the
# audit triggers installed by migration `d1e4a7b9c2f5` could simply be dropped
# by the application process that they are meant to constrain.
#
# This script creates a second, ordinary application role that:
#   * is not a superuser, owns nothing, cannot create databases or roles;
#   * may read and write ordinary tables;
#   * may only INSERT and SELECT on `audit_logs` — never UPDATE, DELETE or
#     TRUNCATE;
#   * has no TRUNCATE privilege on any table at all.
#
# The API then connects as this role (`DATABASE_URL` in docker-compose.prod.yml)
# while migrations continue to run as the owning `POSTGRES_USER`. Idempotent:
# re-running only re-applies the grants, so it is safe after every migration.
#
# This is defence in depth, not a substitute for the trigger. The trigger
# protects the table even where the application *is* the owner (development,
# tests); this role split removes the ability to remove the trigger in
# production. Neither protects against a hostile database administrator.
#
set -euo pipefail

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_APP_USER:?POSTGRES_APP_USER is required}"
: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD is required}"

if [[ "${POSTGRES_APP_USER}" == "${POSTGRES_USER:-}" ]]; then
    echo "POSTGRES_APP_USER must differ from POSTGRES_USER: the application role" \
         "must not be the owning superuser, or the grants below prove nothing." >&2
    exit 1
fi

psql --no-psqlrc --set=ON_ERROR_STOP=1 \
    --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" \
    --set=app_user="${POSTGRES_APP_USER}" \
    --set=app_password="${POSTGRES_APP_PASSWORD}" \
    --set=db_name="${POSTGRES_DB}" <<'SQL'
-- Create the role only if it does not exist; `\gexec` runs the generated
-- statement so no PL/pgSQL dollar-quoting is needed and psql interpolates the
-- password with proper literal quoting (`%L`).
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- Rotate the password on every run, so this script is also the rotation path.
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
              :'app_user', :'app_password')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')
\gexec

-- Ordinary tables: normal read/write, but no TRUNCATE anywhere.
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_user')
\gexec
SELECT format('REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM %I', :'app_user')
\gexec

-- Audit history: append and read only.
SELECT format('REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES ON audit_logs FROM %I', :'app_user')
\gexec
SELECT format('GRANT SELECT, INSERT ON audit_logs TO %I', :'app_user')
\gexec

-- Sequences are needed for any generated identifier the ORM does not supply.
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user')
\gexec

-- Tables created by a future migration (which runs as the owner) inherit the
-- same grants, so a new table does not become unreadable to the API.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL

echo "Application role '${POSTGRES_APP_USER}' provisioned on '${POSTGRES_DB}'."
echo "audit_logs: SELECT, INSERT only (verified by scripts/verify-audit-grants.sh)."
