# Generated API contract

**Do not edit these files by hand.**

- `api.d.ts` is produced by `openapi-typescript` from `apps/web/openapi.json`.
- `apps/web/openapi.json` is produced by the backend's own FastAPI schema
  (`apps/api/tools/export_openapi.py`), not written by hand.

Regenerate both from the repository root:

```bash
make types
```

which runs:

```bash
cd apps/api && python tools/export_openapi.py ../../apps/web/openapi.json
cd apps/web && pnpm types:generate
```

CI's `contract` job repeats those two commands and fails if the committed
document or generated types differ, so a backend schema change cannot leave the
frontend types stale.

The hand-written modules in `src/types/` re-export from `api.d.ts` to keep the
frontend's names (`StudentDetail`, `PortalDocument`, ...). Add new API types
there as aliases; only genuinely UI-only shapes (query-parameter unions,
`FormData` payloads, an error envelope the OpenAPI document cannot describe)
belong in the manual modules.
