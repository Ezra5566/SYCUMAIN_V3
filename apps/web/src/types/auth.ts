import type { components } from "./generated/api";

/**
 * Authentication types — generated from the backend OpenAPI document.
 *
 * `UserRole` stays a literal union: the backend types `Role.name` as a plain
 * string, but navigation and role gating rely on these four values.
 */

type Schemas = components["schemas"];

export type ApiError = import("./api").ApiError;

/** User roles */
export type UserRole = "ADMIN" | "MANAGEMENT" | "TEACHER" | "STUDENT";

/** Role representation */
export type Role = Schemas["RoleResponse"];

/** Authenticated user representation */
export type AuthUser = Schemas["UserResponse"] & {
  /** Present on the login payload; optional so both HTTP paths are assignable. */
  is_superuser?: boolean;
};

/** Login request */
export type LoginRequest = Schemas["LoginRequest"];

/** Login response */
export type LoginResponse = Schemas["LoginResponse"];
