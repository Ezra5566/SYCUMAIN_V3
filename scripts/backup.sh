#!/usr/bin/env bash
#
# Back up a deployed stack: the PostgreSQL database and the document store,
# with a SHA-256 manifest so a restore can prove it recovered the same bytes.
#
#   COMPOSE_PROJECT=sycumain-v3-prod COMPOSE_FILE=docker-compose.prod.yml \
#     COMPOSE_ENV_FILE=.env.production ./scripts/backup.sh
#
# Optional:
#   BACKUP_DIR   host directory for the artifacts (default ./backups)
#   DOCUMENTS_VOLUME  volume name (default <COMPOSE_PROJECT>_documents)
#
# The dump is written to the host, never inside the container or the database
# volume: a backup stored next to the data it protects is not a backup.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_PROJECT="${COMPOSE_PROJECT:?COMPOSE_PROJECT is required}"
COMPOSE_FILE="${COMPOSE_FILE:?COMPOSE_FILE is required}"
COMPOSE_ENV_FILE="${COMPOSE_ENV_FILE:-$ROOT/.env.production}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"

[[ "$COMPOSE_FILE" = /* ]] || COMPOSE_FILE="$ROOT/$COMPOSE_FILE"
[[ "$COMPOSE_ENV_FILE" = /* ]] || COMPOSE_ENV_FILE="$ROOT/$COMPOSE_ENV_FILE"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$ROOT/$BACKUP_DIR"
DOCUMENTS_VOLUME="${DOCUMENTS_VOLUME:-${COMPOSE_PROJECT}_documents}"

mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_TMP="$BACKUP_DIR/.db-$STAMP.part"
DB_FINAL="$BACKUP_DIR/db-$STAMP.dump"
ST_TMP="$BACKUP_DIR/.storage-$STAMP.part"
ST_FINAL="$BACKUP_DIR/storage-$STAMP.tar.gz"
MANIFEST="$BACKUP_DIR/manifest-$STAMP.sha256"
trap 'rm -f "$DB_TMP" "$ST_TMP"' EXIT

compose=(
  docker compose
  -p "$COMPOSE_PROJECT"
  --env-file "$COMPOSE_ENV_FILE"
  -f "$COMPOSE_FILE"
)

fail() {
  echo "ERROR: backup failed: $1" >&2
  exit 1
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

echo "==> waiting for PostgreSQL"
ready=0
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T postgres \
    sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || fail "PostgreSQL did not become ready"

echo "==> dumping the database"
if ! "${compose[@]}" exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  >"$DB_TMP"; then
  fail "pg_dump exited without a usable dump"
fi
[[ -s "$DB_TMP" ]] || fail "database dump is empty"
cat "$DB_TMP" | "${compose[@]}" exec -T postgres pg_restore --list >/dev/null 2>&1 \
  || fail "dump is not a readable PostgreSQL archive"
mv "$DB_TMP" "$DB_FINAL"

echo "==> archiving the document store (volume $DOCUMENTS_VOLUME)"
if docker volume inspect "$DOCUMENTS_VOLUME" >/dev/null 2>&1; then
  docker run --rm -v "$DOCUMENTS_VOLUME":/data:ro alpine \
    tar -czf - -C /data . >"$ST_TMP" || fail "could not archive $DOCUMENTS_VOLUME"
  tar -tzf "$ST_TMP" >/dev/null 2>&1 || fail "document archive is not readable"
  mv "$ST_TMP" "$ST_FINAL"
  echo "    $(tar -tzf "$ST_FINAL" | wc -l | tr -d ' ') entries"
else
  echo "    no such volume; recording that no documents were captured"
  ST_FINAL="none"
fi

{
  echo "sha256 $(basename "$DB_FINAL") $(sha256_of "$DB_FINAL")"
  [[ "$ST_FINAL" == "none" ]] || echo "sha256 $(basename "$ST_FINAL") $(sha256_of "$ST_FINAL")"
} >"$MANIFEST"

cat >"$BACKUP_DIR/latest.txt" <<EOF
database=$DB_FINAL
storage=$ST_FINAL
manifest=$MANIFEST
created=$STAMP
EOF

echo
echo "Backup complete:"
echo "  database: $(basename "$DB_FINAL") ($(wc -c <"$DB_FINAL" | tr -d ' ') bytes)"
echo "  storage:  $(basename "${ST_FINAL}")"
echo "  manifest: $(basename "$MANIFEST")"
echo
echo "Verify it with:"
echo "  COMPOSE_PROJECT=$COMPOSE_PROJECT COMPOSE_FILE=$COMPOSE_FILE \\"
echo "    COMPOSE_ENV_FILE=$COMPOSE_ENV_FILE ./scripts/restore.sh latest"
