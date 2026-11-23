import type { components } from "./generated/api";

/**
 * Immigration types — generated from the backend OpenAPI document.
 *
 * The expiry statuses are computed by the backend and typed as plain strings in
 * the schema, so `ImmigrationDocumentStatus` is exported as the four values the
 * UI renders; it is used for label mapping rather than to re-type the fields.
 */

type Schemas = components["schemas"];

export type ImmigrationDocumentType = Schemas["ImmigrationDocumentType"];

export type ImmigrationDocumentStatus =
  | "VALID"
  | "EXPIRING_SOON"
  | "EXPIRED"
  | "NOT_PROVIDED";

export type ChangeRequestStatus = Schemas["ImmigrationChangeRequestStatus"];

export type ImmigrationDocument = Schemas["ImmigrationDocumentResponse"];

export type ImmigrationProfile = Schemas["ImmigrationProfileResponse"];

export type ImmigrationProfileVersion =
  Schemas["ImmigrationProfileVersionResponse"];

export type ImmigrationChangeRequest =
  Schemas["ImmigrationChangeRequestResponse"];

export type ImmigrationOverviewItem = Schemas["ImmigrationOverviewItem"];

export type ImmigrationOverviewResponse =
  Schemas["ImmigrationOverviewResponse"];

export type NationalityDistribution =
  Schemas["NationalityDistributionResponse"];

export type ImmigrationCohort = Schemas["ImmigrationCohortResponse"];

export type ImmigrationImportRecord = Schemas["ImmigrationImportRecord"];

export type ImmigrationImportPreview =
  Schemas["ImmigrationImportPreviewResponse"];

export type ImmigrationImportApplyResult =
  Schemas["ImmigrationImportApplyResponse"];
