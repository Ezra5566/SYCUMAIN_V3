/** Examination API client.
 *
 * The browser never decides eligibility, publication or conflicts: the server
 * owns all three, and the client renders what it returns. `me()` returns the
 * student shape, whose `result` field is null until the institution publishes.
 */

import { apiFetch } from "@/lib/api";
import type {
  Examination,
  ExaminationDashboard,
  ExaminationDetail,
  ExaminationList,
  ExaminationPayload,
  StudentExaminationList,
} from "@/types/examination";

const BASE = "/api/v1/examinations";

export interface ResultPayload {
  score: number;
  letter_grade?: string | null;
  note?: string | null;
}

export const examinationApi = {
  async list(
    params: {
      search?: string;
      periodId?: string;
      status?: "SCHEDULED" | "CANCELLED";
      published?: "published" | "unpublished";
      page?: number;
      pageSize?: number;
    } = {},
  ): Promise<ExaminationList> {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.periodId) query.set("period_id", params.periodId);
    if (params.status) query.set("status", params.status);
    if (params.published) query.set("published", params.published);
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 25));
    return apiFetch<ExaminationList>(`${BASE}?${query.toString()}`);
  },

  async detail(examinationId: string): Promise<ExaminationDetail> {
    return apiFetch<ExaminationDetail>(`${BASE}/${examinationId}`);
  },

  async dashboard(): Promise<ExaminationDashboard> {
    return apiFetch<ExaminationDashboard>(`${BASE}/dashboard`);
  },

  async mine(): Promise<StudentExaminationList> {
    return apiFetch<StudentExaminationList>(`${BASE}/me`);
  },

  async create(payload: ExaminationPayload): Promise<Examination> {
    return apiFetch<Examination>(BASE, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async update(
    examinationId: string,
    payload: Partial<ExaminationPayload>,
  ): Promise<Examination> {
    return apiFetch<Examination>(`${BASE}/${examinationId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  async cancel(examinationId: string, reason: string): Promise<Examination> {
    return apiFetch<Examination>(`${BASE}/${examinationId}/cancellation`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
  },

  async recordResult(
    examinationId: string,
    studentId: string,
    payload: ResultPayload,
  ): Promise<{ result: { id: string }; result_count: number }> {
    return apiFetch(`${BASE}/${examinationId}/results`, {
      method: "POST",
      body: JSON.stringify({ student_id: studentId, ...payload }),
    });
  },

  async correctResult(
    examinationId: string,
    resultId: string,
    payload: ResultPayload & { reason: string },
  ): Promise<{ result: { id: string }; result_count: number }> {
    return apiFetch(`${BASE}/${examinationId}/results/${resultId}/corrections`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async publish(
    examinationId: string,
  ): Promise<{ examination: Examination; published_count: number }> {
    return apiFetch(`${BASE}/${examinationId}/publication`, { method: "POST" });
  },
};
