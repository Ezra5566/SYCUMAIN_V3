"""Export the FastAPI OpenAPI document to a file.

Run from `apps/api` so the `app` package is importable:

    python tools/export_openapi.py ../../apps/web/openapi.json

This is generation-time tooling only — the API never reads the file. The
frontend generates its TypeScript contract from it, and CI re-runs this command
and fails when the committed document or the generated types are stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tools/export_openapi.py <output.json>", file=sys.stderr)
        return 2

    target = Path(argv[1])
    document = app.openapi()

    # Sorted keys keep the file byte-stable: a schema added elsewhere does not
    # reorder unrelated entries, so the CI diff shows only the real change.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {target} ({len(document['paths'])} paths, "
          f"{len(document['components']['schemas'])} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
