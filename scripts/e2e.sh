#!/usr/bin/env bash
#
# Run the Playwright suite against a dedicated, disposable stack.
#
#   ./scripts/e2e.sh                          # every spec except visual review
#   ./scripts/e2e.sh e2e/smoke.spec.ts        # forwarded to Playwright
#
# Properties this script guarantees:
#   * its own database (`school_portal_e2e`) and compose project, so the
#     development stack on 5435/8001/3101 is never read or written;
#   * its own ports (5436/8002/3002), so it can run while development is up;
#   * a fresh schema and deterministic demo seed on every run;
#   * readiness polling on the API's /ready and a real login page, never a
#     fixed sleep;
#   * teardown with volumes removed on success, failure or interrupt;
#   * service logs preserved as a diagnostic artifact when the run fails.
#
# It refuses to run if the resolved composition targets anything other than the
# disposable database: destructive cleanup must never reach another stack.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/docker-compose.test.yml"
PROJECT="school-portal-v3-e2e"
EXPECTED_DB="school_portal_e2e"
API_URL="http://localhost:8002"
WEB_URL="http://localhost:3002"
RESULTS_DIR="$ROOT/apps/web/test-results"

mkdir -p "$RESULTS_DIR"

compose() {
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# --- Fail closed ------------------------------------------------------------
resolved="$(compose config)"
if ! grep -q "$EXPECTED_DB" <<<"$resolved"; then
  fail "test composition does not target $EXPECTED_DB; refusing to run"
fi
# Portable ERE only: BSD grep has no lookahead, and an unsupported pattern
# would fail the match silently rather than stopping the run.
if grep -qE "school_portal_v2|school_portal_v3" <<<"$resolved"; then
  fail "test composition references a non-test database; refusing to run"
fi

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    compose logs --no-color >"$RESULTS_DIR/docker-failure.log" 2>&1 || true
    echo "Service logs: $RESULTS_DIR/docker-failure.log" >&2
  fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

wait_for_http() {
  local url=$1 label=$2 attempts=${3:-180}
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -o /dev/null --max-time 3 "$url"; then
      echo "ready: $label ($url)"
      return 0
    fi
    sleep 1
  done
  echo "ERROR: $label did not become ready at $url" >&2
  return 1
}

echo "Starting isolated test stack (project $PROJECT)..."
compose down -v --remove-orphans >/dev/null 2>&1 || true
compose up -d --build

wait_for_http "$API_URL/ready" "api readiness"
wait_for_http "$WEB_URL/en/login" "web login page"

echo "Running Playwright against $WEB_URL (api $API_URL)..."
cd "$ROOT/apps/web"
E2E_BASE_URL="$WEB_URL" \
  E2E_API_URL="$API_URL" \
  E2E_PASSWORD="${E2E_PASSWORD:-password123}" \
  npx playwright test "$@"
