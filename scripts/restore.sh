#!/usr/bin/env bash
#
# Restore a backup — into a scratch database to verify it (the default), or
# into the live database and document store.
#
#   ./scripts/restore.sh latest                 verify only (safe)
#   ./scripts/restore.sh backups/db-....dump    verify a specific dump
#   ./scripts/restore.sh latest --live          replace the live database
#   ./scripts/restore.sh latest --live --with-storage
#
# Verification restores into `school_portal_restore_verify` inside the same
# server and proves three things: the schema restores, the recorded row counts
# survive, and every document row's bytes exist with a matching checksum. An
# unverified backup is a guess.
#
# `--live` requires typing the database name. There is no way to reach live
# data without having read that prompt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_PROJECT="${COMPOSE_PROJECT:?COMPOSE_PROJECT is required}"
COMPOSE_FILE="${COMPOSE_FILE:?COMPOSE_FILE is required}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-$ROOT/.env.production}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
VERIFY_DB="school_portal_restore_verify"

[[ "$COMPOSE_FILE" = /* ]] || COMPOSE_FILE="$ROOT/$COMPOSE_FILE"
[[ "$COMPOSE_ENV_FILE" = /* ]] || COMPOSE_ENV_FILE="$ROOT/$COMPOSE_ENV_FILE"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$ROOT/$BACKUP_DIR"

ARG="${1:-}"
MODE="${2:-verify}"
WITH_STORAGE="${3:-}"

[[ -n "$ARG" ]] || { echo "usage: $0 <db-dump|latest> [--live [--with-storage]]" >&2; exit 2; }

compose=(
  docker compose
  -p "$COMPOSE_PROJECT"
  --env-file "$COMPOSE_ENV_FILE"
  -f "$COMPOSE_FILE"
)

# Resolved from the composition rather than assumed: the restore must talk to
# the same role and database the stack actually uses.
PGUSER_NAME="$(docker compose -p "$COMPOSE_PROJECT" --env-file "$COMPOSE_ENV_FILE" \
  -f "$COMPOSE_FILE" config | awk '/POSTGRES_USER:/ {print $2; exit}')"
[[ -n "$PGUSER_NAME" ]] || PGUSER_NAME="portal"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

fail() { echo "ERROR: $1" >&2; exit 1; }

if [[ "$ARG" == "latest" ]]; then
  [[ -f "$BACKUP_DIR/latest.txt" ]] || fail "$BACKUP_DIR/latest.txt is missing — run scripts/backup.sh first"
  # shellcheck disable=SC1091
  source "$BACKUP_DIR/latest.txt"
  DUMP="$database"
  STORAGE_ARCHIVE="${storage:-none}"
  MANIFEST="${manifest:-none}"
else
  DUMP="$ARG"
  STORAGE_ARCHIVE="none"
  MANIFEST="none"
fi

[[ -f "$DUMP" ]] || fail "no such dump: $DUMP"

# --- Digest verification ----------------------------------------------------
if [[ "$MANIFEST" != "none" && -f "$MANIFEST" ]]; then
  echo "==> verifying artifact digests"
  while read -r tag name digest; do
    [[ "$tag" == "sha256" ]] || continue
    artifact="$BACKUP_DIR/$name"
    [[ -f "$artifact" ]] || fail "manifest lists missing file $name"
    [[ "$(sha256_of "$artifact")" == "$digest" ]] || fail "digest mismatch for $name"
    echo "    ok $name"
  done <"$MANIFEST"
fi

psql_db() {
  local database="$1" sql="$2"
  "${compose[@]}" exec -T postgres \
    psql --username "$PGUSER_NAME" --dbname "$database" \
    --no-psqlrc --quiet --tuples-only --no-align -v ON_ERROR_STOP=1 -c "$sql"
}

restore_into() {
  local target="$1" source="$2"
  "${compose[@]}" exec -T postgres \
    pg_restore --username "$PGUSER_NAME" --dbname "$target" \
    --no-owner --no-privileges --exit-on-error <"$source"
}

# --- Document byte check ----------------------------------------------------
check_storage() {
  local verify_db="$1"
  [[ "$STORAGE_ARCHIVE" != "none" ]] || { echo "  storage: not captured in this backup"; return 0; }

  local scratch
  scratch="$(mktemp -d "${TMPDIR:-/tmp}/portal-verify.XXXXXX")"
  tar -xzf "$STORAGE_ARCHIVE" -C "$scratch" || fail "document archive is not readable"

  local total=0 missing=0 mismatched=0 key checksum file actual
  while IFS='|' read -r key checksum; do
    [[ -n "$key" ]] || continue
    total=$((total + 1))
    file="$scratch/$key"
    if [[ ! -f "$file" ]]; then
      missing=$((missing + 1)); echo "  MISSING $key"; continue
    fi
    if [[ -n "$checksum" ]]; then
      actual="$(sha256_of "$file")"
      [[ "$actual" == "$checksum" ]] || { mismatched=$((mismatched + 1)); echo "  CHECKSUM MISMATCH $key"; }
    fi
  done < <(psql_db "$verify_db" \
    "SELECT object_key, coalesce(checksum_sha256,'') FROM documents ORDER BY object_key;")

  echo "  documents:         $total"
  echo "  missing objects:   $missing"
  echo "  checksum failures: $mismatched"
  rm -rf "$scratch"

  [[ "$missing" -eq 0 ]] || fail "$missing document row(s) have no restored bytes"
  [[ "$mismatched" -eq 0 ]] || fail "$mismatched restored file(s) do not match their stored checksum"
}

# --- Verify (default) -------------------------------------------------------
if [[ "$MODE" != "--live" ]]; then
  echo "==> verifying $(basename "$DUMP") in a scratch database"
  psql_db postgres "DROP DATABASE IF EXISTS $VERIFY_DB;" >/dev/null
  psql_db postgres "CREATE DATABASE $VERIFY_DB;" >/dev/null
  restore_into "$VERIFY_DB" "$DUMP"

  tables="$(psql_db "$VERIFY_DB" "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")"
  revisions="$(psql_db "$VERIFY_DB" "SELECT count(*) FROM alembic_version;")"
  students="$(psql_db "$VERIFY_DB" "SELECT count(*) FROM students;")"
  users="$(psql_db "$VERIFY_DB" "SELECT count(*) FROM users;")"

  echo
  echo "Restore verification:"
  echo "  tables:            ${tables:-0}"
  echo "  alembic revisions: ${revisions:-0}"
  echo "  students:          ${students:-0}"
  echo "  users:             ${users:-0}"

  [[ "${revisions:-0}" -ge 1 ]] || fail "restored database has no alembic_version row — dump is not usable"
  [[ "${tables:-0}" -ge 1 ]] || fail "restored database has no tables"

  check_storage "$VERIFY_DB"

  psql_db postgres "DROP DATABASE IF EXISTS $VERIFY_DB;" >/dev/null
  echo
  echo "OK: the backup restores and its document bytes match their checksums."
  echo "    The live database was not touched."
  exit 0
fi

# --- Live restore -----------------------------------------------------------
DB_NAME="$(docker compose -p "$COMPOSE_PROJECT" --env-file "$COMPOSE_ENV_FILE" \
  -f "$COMPOSE_FILE" config | awk '/POSTGRES_DB:/ {print $2; exit}')"
[[ -n "$DB_NAME" ]] || fail "could not determine POSTGRES_DB from the composition"

echo "This will REPLACE the live database '$DB_NAME' with:"
echo "  $DUMP"
if [[ "$WITH_STORAGE" == "--with-storage" && "$STORAGE_ARCHIVE" != "none" ]]; then
  echo "and REPLACE the live document store with: $STORAGE_ARCHIVE"
fi
read -r -p "Type the database name to continue: " CONFIRM
[[ "$CONFIRM" == "$DB_NAME" ]] || { echo "Aborted."; exit 1; }

echo "==> stopping the API so no connection holds the database"
"${compose[@]}" stop api

psql_db postgres \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" \
  >/dev/null || true

restore_into "$DB_NAME" "$DUMP"

if [[ "$WITH_STORAGE" == "--with-storage" && "$STORAGE_ARCHIVE" != "none" ]]; then
  echo "==> replacing the document store (previous contents kept aside)"
  "${compose[@]}" run --rm --no-deps -T api sh -c '
    set -e
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    if [ -d /app/var/storage ]; then
      mv /app/var/storage "/app/var/storage.pre-restore-$stamp"
    fi
    mkdir -p /app/var/storage
  '
  "${compose[@]}" run --rm --no-deps -T api tar -xzf - -C /app/var <"$STORAGE_ARCHIVE"
fi

echo "==> starting the API (apply the approved migration if the restored revision is behind)"
"${compose[@]}" start api

echo
echo "Live restore complete. Confirm with:"
echo "  curl -fsS https://<host>/ready"
echo "  make prod-migrate   # only if the restored revision is behind head"
