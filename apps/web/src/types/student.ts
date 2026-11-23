import type { components } from "./generated/api";

/**
 * Student types — generated from the backend OpenAPI document.
 *
 * Request bodies and responses use the generated optionality, which is what the
 * document declares; the UI treats a missing nullable field as null.
 *
 * `StudentSort` and `ImmigrationStatusFilter` are query-parameter domains, not
 * schemas, so they remain manual.
 */

type Schemas = components["schemas"];

export type StudentStatus = Schemas["StudentStatus"];

export type StudentBrief = Schemas["StudentBrief"];

export type StudentDetail = Schemas["StudentDetail"];

export type StudentListResponse = Schemas["StudentListResponse"];

export type StudentCreate = Schemas["StudentCreate"];

export type StudentUpdate = Schemas["StudentUpdate"];

/** Filter and sort options the directory endpoint accepts. */
export type StudentSort =
  | "name"
  | "-name"
  | "student_number"
  | "-student_number"
  | "newest"
  | "oldest";

/** The buckets the backend derives from immigration expiry dates. */
export type ImmigrationStatusFilter =
  | "VALID"
  | "EXPIRING_SOON"
  | "URGENT"
  | "EXPIRED"
  | "NOT_PROVIDED";

/**
 * Onboarding request: creates the student record and its login account in one
 * transaction. The response carries a one-time temporary password.
 */
export type StudentOnboard = Schemas["StudentOnboard"];

export type StudentAccount = Schemas["StudentAccountResponse"];

export type StudentOnboardedResponse = Schemas["StudentOnboardedResponse"];

/** Fields a student may change on their own record. */
export type StudentSelfUpdate = Schemas["StudentSelfUpdate"];

export type BulkResultItem = Schemas["BulkResultItem"];

export type StudentBulkResponse = Schemas["StudentBulkResponse"];

/** One row of a bulk intake report. */
export type StudentImportRow = Schemas["StudentImportRow"];

/**
 * Result of validating or applying an intake file.
 *
 * `aborted` means invalid rows caused every write to be refused — the file was
 * read successfully, but nothing was imported.
 */
export type StudentImportReport = Schemas["StudentImportReport"];
