#!/usr/bin/env bash
#
# Start the presentation environment.
#
#   ./scripts/demo-up.sh
#
# This is the development composition with the synthetic demonstration cohort
# (1,500+ synthetic students, the full housing estate, academic catalogue and
# immigration profiles). It is deliberately not the production composition:
#
#   * the demo seed accounts must exist, and production refuses to seed them;
#   * the database keeps its data between runs, so a rehearsal does not start
#     from an empty portal;
#   * the API speaks plain HTTP on loopback, because the presentation is on the
#     presenter's own machine.
#
# Nothing here touches the V1 reference installation or the production stack.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_URL="http://localhost:8001"
WEB_URL="http://localhost:3101"

echo "Starting the portal (existing database is preserved)..."
docker compose up -d --build

wait_for() {
  local url=$1 label=$2 attempts=${3:-180}
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -o /dev/null --max-time 3 "$url"; then
      echo "ready: $label"
      return 0
    fi
    sleep 1
  done
  echo "ERROR: $label did not become ready at $url" >&2
  docker compose logs --tail 40 api web >&2 || true
  return 1
}

wait_for "$API_URL/ready" "api readiness"
wait_for "$WEB_URL/en/login" "web login page"

# Next compiles a route the first time it is requested in development mode; a
# cold announcements page was measured at 100 s. Request every route the
# demonstration visits, once, so the presenter never waits for a compile.
echo
echo "Preparing routes (first-run compile, then cached)..."
for route in \
  /en/login /en/app /en/app/students /en/app/academics /en/app/academics/calendar \
  /en/app/housing /en/app/immigration /en/app/announcements /en/app/reports \
  /en/app/audit /en/app/settings /en/app/profile /en/app/attendance /ar/app; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 240 "$WEB_URL$route" || echo 000)
  echo "  $code  $route"
  if [ "$code" = "000" ]; then
    echo "ERROR: $route did not answer; see: docker compose logs web" >&2
    exit 1
  fi
done

echo
echo "Preparing the four presentation accounts..."
python3 "$ROOT/scripts/demo_accounts.py"

cat <<EOF

Presentation environment is ready.

  Portal        $WEB_URL/en/login
  API health    $API_URL/ready
  Arabic (RTL)  $WEB_URL/ar/login

  Accounts      python3 scripts/demo_accounts.py --show
  Credentials   $ROOT/.demo-credentials.json  (mode 0600)

Stop with:      ./scripts/demo-down.sh
EOF
