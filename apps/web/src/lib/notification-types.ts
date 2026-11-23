/**
 * Maps a notification type to the message key that carries its human-readable
 * text. Adding a backend notification type requires only a new entry here plus
 * the message — no changes to the rendering logic.
 *
 * Types absent from this map render only their label, which is the correct
 * degradation: a bare status chip is better than an invented sentence.
 *
 * The API stores a machine-readable type plus parameters (never English prose),
 * so the sentence is composed in the reader's language on the client.
 */
export const NOTIFICATION_TYPE_MESSAGE_KEY: Record<string, string> = {
  IMMIGRATION_CHANGE_SUBMITTED: "immigrationSubmitted",
  IMMIGRATION_CHANGE_APPROVED: "immigrationApproved",
  IMMIGRATION_CHANGE_REJECTED: "immigrationRejected",
  IMMIGRATION_DOCUMENT_UPLOADED: "immigrationDocumentUploaded",
  HOUSING_ASSIGNMENT_CREATED: "housingAssigned",
  HOUSING_ASSIGNMENT_TRANSFERRED: "housingTransferred",
  HOUSING_ASSIGNMENT_ENDED: "housingEnded",
  SUPPORT_TICKET_CREATED: "supportCreated",
  SUPPORT_TICKET_REPLIED: "supportReplied",
  SUPPORT_TICKET_STATUS_CHANGED: "supportStatusChanged",
  SUPPORT_TICKET_ASSIGNED: "supportAssigned",
  ANNOUNCEMENT_PUBLISHED: "announcementPublished",
  DOCUMENT_UPLOADED: "documentUploaded",
};

/** Message key for a type, or null when the type has no sentence. */
export function notificationMessageKey(type: string): string | null {
  return NOTIFICATION_TYPE_MESSAGE_KEY[type] ?? null;
}
