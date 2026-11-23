/**
 * Attendance commencement API client.
 *
 * The frontend never derives a commencement date or decides who may approve
 * one: it shows the server's suggestion and sends back the suggestion the
 * approver explicitly confirmed.
 */

import { apiFetch } from "@/lib/api";
import type {
  CommencementInput,
  CommencementListResponse,
  CommencementRecord,
  CommencementStatusFilter,
  CommencementSummary,
} from "@/types/commencement";

const BASE = "/api/v1/attendance";

class CommencementApiClient {
  async list(
    params: {
      status?: CommencementStatusFilter;
      search?: string;
      page?: number;
      page_size?: number;
    } = {},
  ): Promise<CommencementListResponse> {
    const searchParams = new URLSearchParams();
    if (params.status) searchParams.set("status", params.status);
    if (params.search) searchParams.set("search", params.search);
    if (params.page) searchParams.set("page", String(params.page));
    if (params.page_size) searchParams.set("page_size", String(params.page_size));
    const query = searchParams.toString();
    return apiFetch<CommencementListResponse>(
      `${BASE}/commencements${query ? `?${query}` : ""}`,
    );
  }

  async summary(
    studentId: string,
    admissionId: string,
  ): Promise<CommencementSummary> {
    return apiFetch<CommencementSummary>(
      `${BASE}/students/${studentId}/admissions/${admissionId}/commencement`,
    );
  }

  async approve(
    studentId: string,
    admissionId: string,
    input: CommencementInput,
  ): Promise<CommencementRecord> {
    return apiFetch<CommencementRecord>(
      `${BASE}/students/${studentId}/admissions/${admissionId}/commencement`,
      { method: "POST", body: JSON.stringify(input) },
    );
  }

  async correct(
    studentId: string,
    admissionId: string,
    input: CommencementInput,
  ): Promise<CommencementRecord> {
    return apiFetch<CommencementRecord>(
      `${BASE}/students/${studentId}/admissions/${admissionId}/commencement/corrections`,
      { method: "POST", body: JSON.stringify(input) },
    );
  }
}

export const commencementApi = new CommencementApiClient();
