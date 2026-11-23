import type { components } from "./generated/api";

/**
 * Account lifecycle types — generated from the backend OpenAPI document.
 *
 * Password material appears only in `temporary_password`, which the backend
 * returns exactly once at creation or reset.
 */

type Schemas = components["schemas"];

export type RoleName = "ADMIN" | "MANAGEMENT" | "TEACHER" | "STUDENT";

export const ROLE_NAMES: RoleName[] = [
  "ADMIN",
  "MANAGEMENT",
  "TEACHER",
  "STUDENT",
];

export type AccountRoleInfo = Schemas["AccountRoleInfo"];

export type Account = Schemas["AccountResponse"];

export type AccountListResponse = Schemas["AccountListResponse"];

/** Returned once, at creation. The password cannot be retrieved later. */
export type AccountCreatedResponse = Schemas["AccountCreatedResponse"];

/**
 * Admin password reset result.
 *
 * Not in the OpenAPI components: the endpoint returns it directly without a
 * declared response model, so it stays manual until that changes.
 */
export interface PasswordResetResponse {
  user_id: string;
  temporary_password: string;
  must_change_password: boolean;
  sessions_revoked: number;
}

export type SessionInfo = Schemas["SessionInfo"];

export type SessionListResponse = Schemas["SessionListResponse"];

export type PasswordChangeResponse = Schemas["PasswordChangeResponse"];
