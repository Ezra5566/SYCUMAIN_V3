import type { components } from "./generated/api";

/**
 * Types for the platform layer — generated from the backend OpenAPI document.
 *
 * Enum values are the raw machine-readable strings the backend emits; the UI
 * turns them into localized labels.
 *
 * `Announcement` adds `title`/`summary`: the detail endpoint returns
 * `resolved_title` and translations, while the UI header and breadcrumbs read a
 * top-level title. `UploadDocumentInput` stays manual because it is a `FormData`
 * payload, not a JSON schema.
 */

type Schemas = components["schemas"];

export type AnnouncementStatus = Schemas["AnnouncementStatus"];

export type AnnouncementPriority = Schemas["AnnouncementPriority"];

export type AnnouncementAudienceType = Schemas["AnnouncementAudienceType"];

export type AnnouncementTranslation =
  Schemas["AnnouncementTranslationResponse"];

export type AnnouncementListItem = Schemas["AnnouncementListItem"];

export type Announcement = Schemas["AnnouncementResponse"] & {
  title?: string;
  summary?: string | null;
};

export type AnnouncementListResponse =
  Schemas["AnnouncementListResponse"];

export type AnnouncementTranslationInput =
  Schemas["AnnouncementTranslationInput"];

export type AnnouncementCreateInput = Schemas["AnnouncementCreate"];

export type SupportTicketStatus = Schemas["SupportTicketStatus"];

export type SupportTicketCategory = Schemas["SupportTicketCategory"];

export type PlatformPriority = Schemas["SupportTicketPriority"];

export type SupportTicketMessage =
  Schemas["SupportTicketMessageResponse"];

export type SupportTicketListItem = Schemas["SupportTicketListItem"];

export type SupportTicket = Schemas["SupportTicketResponse"];

export type SupportTicketListResponse =
  Schemas["SupportTicketListResponse"];

export type SupportTicketStats = Schemas["SupportTicketStatsResponse"];

export type CreateSupportTicketInput = Schemas["SupportTicketCreate"];

export type UpdateSupportTicketInput = Schemas["SupportTicketUpdate"];

export type NotificationType = Schemas["NotificationType"];

export type PortalNotification = Schemas["NotificationResponse"];

export type NotificationListResponse = Schemas["NotificationListResponse"];

export type DocumentStatus = Schemas["DocumentStatus"];

export type DocumentVisibility = Schemas["DocumentVisibility"];

export type DocumentReviewStatus = Schemas["DocumentReviewStatus"];

/** Document metadata. Never carries a storage key. */
export type PortalDocument = Schemas["DocumentResponse"];

/** A selectable document category, served by the API. */
export type DocumentTypeOption = Schemas["DocumentTypeOption"];

export type RequiredDocumentState =
  | "MISSING"
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "REPLACEMENT_REQUIRED"
  | "EXPIRING"
  | "EXPIRED";

/** One expected document category and whether the student has supplied it. */
export type RequiredDocumentStatus = Schemas["RequiredDocumentStatus"];

/** Per-student document completeness, for the profile Documents tab. */
export type StudentDocumentSummary = Schemas["StudentDocumentSummary"];

export type DocumentListResponse = Schemas["DocumentListResponse"];

/** Multipart upload payload — a browser `FormData` shape, not JSON. */
export interface UploadDocumentInput {
  file: File;
  document_type: string;
  title: string;
  description?: string;
  student_id?: string;
  student_visible?: boolean;
}

export type AuditLogEntry = Schemas["AuditLogResponse"];

export type AuditLogListResponse = Schemas["AuditLogListResponse"];

/** A labelled count used by report breakdown tables. */
export type CountItem = Schemas["CountItem"];

export type StudentReport = Schemas["StudentReport"];

export type ImmigrationReport = Schemas["ImmigrationReport"];

export type HousingReport = Schemas["HousingReport"];

export type AcademicReport = Schemas["AcademicReport"];

export type OperationsReport = Schemas["OperationsReport"];
