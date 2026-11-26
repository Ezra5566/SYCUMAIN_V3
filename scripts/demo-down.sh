#!/usr/bin/env bash
#
# Stop the presentation environment without destroying it.
#
#   ./scripts/demo-down.sh
#
# The containers stop; the PostgreSQL volume, uploaded documents and the demo
# accounts are kept, so the next `./scripts/demo-up.sh` resumes the same
# portal. Nothing is deleted — this script never runs `down -v`, drops a
# database or rewrites a record.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

docker compose stop
echo "Stopped. Data, documents and accounts are preserved."
