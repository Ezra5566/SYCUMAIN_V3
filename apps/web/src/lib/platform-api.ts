/**
 * API client for the Stage 7 platform modules.
 *
 * Built on the same session cookie and error contract as the rest of the app.
 * Two helpers deliberately bypass the JSON wrapper: multipart uploads must let
 * the browser set the `Content-Type` boundary, and downloads must stream bytes
 * rather than parse JSON.
 */

import { API_BASE, apiFetch } from "@/lib/api";
import { apiErrorFromResponse } from "@/lib/api-error";
import type {
  AcademicReport,
  Announcement,
  AnnouncementCreateInput,
  AnnouncementListResponse,
  AuditLogListResponse,
  CreateSupportTicketInput,
  DocumentListResponse,
  DocumentReviewStatus,
  DocumentTypeOption,
  HousingReport,
  ImmigrationReport,
  NotificationListResponse,
  OperationsReport,
  PortalDocument,
  PortalNotification,
  StudentDocumentSummary,
  StudentReport,
  SupportTicket,
  SupportTicketListResponse,
  SupportTicketMessage,
  SupportTicketStats,
  UpdateSupportTicketInput,
  UploadDocumentInput,
} from "@/types/platform";

function query(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/**
 * The announcements API localizes content server-side, so the caller's locale
 * travels as `Accept-Language` rather than as a query parameter the client
 * could tamper with to read arbitrary translations.
 */
function localeHeaders(locale?: string): Record<string, string> {
  return locale ? { "Accept-Language": locale } : {};
}

// --- Announcements ---------------------------------------------------------

export const announcementApi = {
  list: (
    params: {
      locale?: string;
      status?: string;
      audience?: string;
      search?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) => {
    const { locale, ...rest } = params;
    return apiFetch<AnnouncementListResponse>(`/api/v1/announcements${query(rest)}`, {
      headers: localeHeaders(locale),
    });
  },

  get: (id: string, locale?: string) =>
    apiFetch<Announcement>(`/api/v1/announcements/${id}`, {
      headers: localeHeaders(locale),
    }),

  create: (payload: AnnouncementCreateInput) =>
    apiFetch<Announcement>("/api/v1/announcements", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  update: (id: string, payload: Partial<AnnouncementCreateInput>) =>
    apiFetch<Announcement>(`/api/v1/announcements/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  publish: (id: string) =>
    apiFetch<Announcement>(`/api/v1/announcements/${id}/publish`, { method: "POST" }),

  archive: (id: string) =>
    apiFetch<Announcement>(`/api/v1/announcements/${id}/archive`, { method: "POST" }),
};

// --- Support ---------------------------------------------------------------

export const supportApi = {
  list: (params: {
    status?: string;
    category?: string;
    assigned_to_me?: boolean;
    student_id?: string;
    search?: string;
    page?: number;
    page_size?: number;
  } = {}) => apiFetch<SupportTicketListResponse>(`/api/v1/support${query(params)}`),

  stats: () => apiFetch<SupportTicketStats>("/api/v1/support/stats"),

  get: (id: string) => apiFetch<SupportTicket>(`/api/v1/support/${id}`),

  create: (payload: CreateSupportTicketInput) =>
    apiFetch<SupportTicket>("/api/v1/support", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  update: (id: string, payload: UpdateSupportTicketInput) =>
    apiFetch<SupportTicket>(`/api/v1/support/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  addMessage: (id: string, body: string, isInternal = false) =>
    apiFetch<SupportTicketMessage>(`/api/v1/support/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ body, is_internal: isInternal }),
    }),
};

// --- Notifications ---------------------------------------------------------

export const notificationApi = {
  list: (params: { unread_only?: boolean; page?: number; page_size?: number } = {}) =>
    apiFetch<NotificationListResponse>(`/api/v1/notifications${query(params)}`),

  unreadCount: () =>
    apiFetch<{ unread_count: number }>("/api/v1/notifications/unread-count"),

  markRead: (id: string) =>
    apiFetch<PortalNotification>(`/api/v1/notifications/${id}/read`, { method: "POST" }),

  markAllRead: () =>
    apiFetch<{ updated: number }>("/api/v1/notifications/read-all", { method: "POST" }),
};

// --- Documents -------------------------------------------------------------

export const documentApi = {
  list: (
    params: {
      student_id?: string;
      document_type?: string;
      search?: string;
      include_archived?: boolean;
      page?: number;
      page_size?: number;
    } = {},
  ) => apiFetch<DocumentListResponse>(`/api/v1/documents${query(params)}`),

  get: (id: string) => apiFetch<PortalDocument>(`/api/v1/documents/${id}`),

  /**
   * Upload a document.
   *
   * `Content-Type` is intentionally absent: the browser must generate the
   * multipart boundary, and the backend validates the real file type from the
   * bytes rather than trusting whatever the client declares.
   */
  upload: async (input: UploadDocumentInput): Promise<PortalDocument> => {
    const form = new FormData();
    form.append("file", input.file);
    form.append("document_type", input.document_type);
    form.append("title", input.title);
    if (input.description) form.append("description", input.description);
    if (input.student_id) form.append("student_id", input.student_id);
    form.append("student_visible", String(input.student_visible ?? false));

    const response = await fetch(`${API_BASE}/api/v1/documents`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.json() as Promise<PortalDocument>;
  },

  archive: (id: string) =>
    apiFetch<void>(`/api/v1/documents/${id}`, { method: "DELETE" }),

  /**
   * Document completeness for one student.
   *
   * "You are missing your residence permit" is a different answer from "here
   * are four files", and the API is where that distinction lives — it knows
   * which categories are institutionally required.
   */
  summary: (studentId: string) =>
    apiFetch<StudentDocumentSummary>(
      `/api/v1/documents/students/${studentId}/summary`,
    ),

  /** The vocabulary of document categories, so the UI is not its arbiter. */
  types: () =>
    apiFetch<{ items: DocumentTypeOption[] }>("/api/v1/documents/types"),

  /**
   * Approve or reject an uploaded document.
   *
   * The API refuses a rejection with no note (`REJECTION_NOTE_REQUIRED`), which
   * the caller renders — a student told only "rejected" cannot act on it.
   */
  review: (
    id: string,
    input: {
      decision: DocumentReviewStatus;
      note?: string;
    },
  ) =>
    apiFetch<PortalDocument>(`/api/v1/documents/${id}/review`, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  /** Flag a document as institutionally required and/or set its expiry. */
  setExpectation: (
    id: string,
    input: { is_required?: boolean; expires_on?: string | null },
  ) =>
    apiFetch<PortalDocument>(`/api/v1/documents/${id}/expectation`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),

  /**
   * Upload a new version of an existing document.
   *
   * Replacing never overwrites history: the previous version is marked
   * superseded and the new one starts its own review cycle.
   */
  replace: async (
    id: string,
    input: { file: File; title?: string; description?: string; expires_on?: string },
  ): Promise<PortalDocument> => {
    const form = new FormData();
    form.append("file", input.file);
    if (input.title) form.append("title", input.title);
    if (input.description) form.append("description", input.description);
    if (input.expires_on) form.append("expires_on", input.expires_on);

    const response = await fetch(`${API_BASE}/api/v1/documents/${id}/replace`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.json() as Promise<PortalDocument>;
  },

  /**
   * Download a document as a blob.
   *
   * Fetched rather than linked so the session cookie is sent and a 401/403 is
   * surfaced as a real error instead of silently saving an error page.
   */
  download: async (id: string, filename: string): Promise<void> => {
    const response = await fetch(`${API_BASE}/api/v1/documents/${id}/download`, {
      credentials: "include",
    });
    if (!response.ok) throw await apiErrorFromResponse(response);

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },

  /** Fetch a previewable document as a blob without exposing a public URL. */
  preview: async (id: string): Promise<{ blob: Blob; contentType: string }> => {
    const response = await fetch(`${API_BASE}/api/v1/documents/${id}/preview`, {
      credentials: "include",
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    return {
      blob: await response.blob(),
      contentType:
        response.headers.get("content-type") ?? "application/octet-stream",
    };
  },
};

// --- Reports ---------------------------------------------------------------

export const reportApi = {
  overview: () => apiFetch<OperationsReport>("/api/v1/reports/overview"),
  students: () => apiFetch<StudentReport>("/api/v1/reports/students"),
  immigration: () => apiFetch<ImmigrationReport>("/api/v1/reports/immigration"),
  housing: () => apiFetch<HousingReport>("/api/v1/reports/housing"),
  academics: () => apiFetch<AcademicReport>("/api/v1/reports/academics"),
};

// --- Audit -----------------------------------------------------------------

export const auditApi = {
  list: (params: {
    action?: string;
    entity_type?: string;
    page?: number;
    page_size?: number;
  } = {}) => apiFetch<AuditLogListResponse>(`/api/v1/audit${query(params)}`),
};
