import type { components } from "./generated/api";

/**
 * Shared API types.
 *
 * `generated/api.d.ts` is produced from the backend OpenAPI document — never
 * edit it. Regenerate with `pnpm types:generate` after exporting the spec
 * (`python tools/export_openapi.py ../../apps/web/openapi.json`).
 *
 * `ApiError` is deliberately manual: error bodies are raised as `HTTPException`
 * details rather than declared response models, so the document has no schema
 * for them. List responses use their own generated `*ListResponse` types.
 */

type Schemas = components["schemas"];

export type HealthResponse = Schemas["HealthResponse"];
export type ReadyResponse = Schemas["ReadyResponse"];

/** Standard API error response. */
export interface ApiError {
  error: {
    code: string;
    message: string;
    request_id?: string;
  };
}

