/** Immigration API client */

import { API_BASE, apiFetch } from "@/lib/api";
import { apiErrorFromResponse } from "@/lib/api-error";
import type {
  ImmigrationCohort,
  ImmigrationProfile,
  ImmigrationChangeRequest,
  ImmigrationImportApplyResult,
  ImmigrationImportPreview,
  ImmigrationImportRecord,
  ImmigrationOverviewResponse,
  NationalityDistribution,
  ImmigrationDocument,
  ImmigrationProfileVersion,
} from "@/types/immigration";

export async function getStudentImmigration(
  studentId: string
): Promise<ImmigrationProfile> {
  return apiFetch<ImmigrationProfile>(
    `/api/v1/students/${studentId}/immigration`
  );
}

export async function updateStudentImmigration(
  studentId: string,
  data: Record<string, unknown>
): Promise<ImmigrationProfile> {
  return apiFetch<ImmigrationProfile>(
    `/api/v1/students/${studentId}/immigration`,
    { method: "PATCH", body: JSON.stringify(data) }
  );
}

export async function getImmigrationHistory(
  studentId: string
): Promise<ImmigrationProfileVersion[]> {
  return apiFetch<ImmigrationProfileVersion[]>(
    `/api/v1/students/${studentId}/immigration/history`
  );
}

export async function submitChangeRequest(
  studentId: string,
  changeType: string,
  proposedData: Record<string, unknown>
): Promise<ImmigrationChangeRequest> {
  return apiFetch<ImmigrationChangeRequest>(
    `/api/v1/students/${studentId}/immigration/change-requests`,
    {
      method: "POST",
      body: JSON.stringify({
        change_type: changeType,
        proposed_data: proposedData,
      }),
    }
  );
}

export async function listChangeRequests(
  status?: string
): Promise<ImmigrationChangeRequest[]> {
  const params = status ? `?status=${status}` : "";
  return apiFetch<ImmigrationChangeRequest[]>(
    `/api/v1/immigration/change-requests${params}`
  );
}

export async function getChangeRequest(
  requestId: string
): Promise<ImmigrationChangeRequest> {
  return apiFetch<ImmigrationChangeRequest>(
    `/api/v1/immigration/change-requests/${requestId}`
  );
}

export async function approveChangeRequest(
  requestId: string
): Promise<ImmigrationChangeRequest> {
  return apiFetch<ImmigrationChangeRequest>(
    `/api/v1/immigration/change-requests/${requestId}/approve`,
    { method: "POST" }
  );
}

export async function rejectChangeRequest(
  requestId: string,
  reason?: string
): Promise<ImmigrationChangeRequest> {
  return apiFetch<ImmigrationChangeRequest>(
    `/api/v1/immigration/change-requests/${requestId}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ rejection_reason: reason || null }),
    }
  );
}

export async function getStudentImmigrationCohort(
  studentId: string
): Promise<ImmigrationCohort> {
  return apiFetch<ImmigrationCohort>(
    `/api/v1/students/${studentId}/immigration/cohort`
  );
}

export async function getImmigrationOverview(params: {
  status?: string;
  intakeId?: string;
  page?: number;
  pageSize?: number;
} = {}): Promise<ImmigrationOverviewResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.intakeId) search.set("intake_id", params.intakeId);
  if (params.page) search.set("page", String(params.page));
  if (params.pageSize) search.set("page_size", String(params.pageSize));
  const query = search.toString();
  return apiFetch<ImmigrationOverviewResponse>(
    `/api/v1/immigration/overview${query ? `?${query}` : ""}`
  );
}

export async function getNationalityDistribution(
  intakeId?: string,
): Promise<NationalityDistribution> {
  const query = intakeId ? `?intake_id=${encodeURIComponent(intakeId)}` : "";
  return apiFetch<NationalityDistribution>(
    `/api/v1/immigration/countries${query}`,
  );
}

export async function exportImmigrationOverview(params: {
  status?: string;
  intakeId?: string;
} = {}): Promise<Blob> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.intakeId) search.set("intake_id", params.intakeId);
  const query = search.toString();
  const response = await fetch(
    `${API_BASE}/api/v1/immigration/overview/export${query ? `?${query}` : ""}`,
    { credentials: "include" },
  );
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

export async function previewImmigrationImport(input: {
  source_reference: string;
  records: ImmigrationImportRecord[];
}): Promise<ImmigrationImportPreview> {
  return apiFetch<ImmigrationImportPreview>(
    "/api/v1/immigration/import/preview",
    { method: "POST", body: JSON.stringify(input) }
  );
}

export async function applyImmigrationImport(input: {
  source_reference: string;
  records: ImmigrationImportRecord[];
  confirm: true;
}): Promise<ImmigrationImportApplyResult> {
  return apiFetch<ImmigrationImportApplyResult>(
    "/api/v1/immigration/import/apply",
    { method: "POST", body: JSON.stringify(input) }
  );
}

export async function listStudentDocuments(
  studentId: string
): Promise<ImmigrationDocument[]> {
  return apiFetch<ImmigrationDocument[]>(
    `/api/v1/students/${studentId}/immigration/documents`
  );
}
