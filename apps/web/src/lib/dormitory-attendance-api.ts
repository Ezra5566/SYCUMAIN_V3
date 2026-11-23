/** Dormitory attendance API client.
 *
 * The client never derives points or eligibility: the server resolves which
 * housing stay an absence belongs to and whether the student was resident that
 * day, so the browser only sends what was entered and renders what comes back.
 */

import { apiFetch } from "@/lib/api";
import type {
  DormitoryAbsenceResult,
  DormitoryStudentDetail,
  DormitoryStudentList,
} from "@/types/dormitory-attendance";

const BASE = "/api/v1/dormitory";

export const dormitoryApi = {
  async listStudents(
    params: {
      search?: string;
      residency?: "all" | "current" | "former";
      page?: number;
      pageSize?: number;
    } = {},
  ): Promise<DormitoryStudentList> {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.residency) query.set("residency", params.residency);
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 25));
    return apiFetch<DormitoryStudentList>(`${BASE}/students?${query.toString()}`);
  },

  async detail(studentId: string): Promise<DormitoryStudentDetail> {
    return apiFetch<DormitoryStudentDetail>(`${BASE}/students/${studentId}`);
  },

  async record(
    studentId: string,
    body: { absence_date: string; points: number; reason: string },
  ): Promise<DormitoryAbsenceResult> {
    return apiFetch<DormitoryAbsenceResult>(
      `${BASE}/students/${studentId}/absences`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  async correct(
    studentId: string,
    absenceId: string,
    body: { absence_date: string; points: number; reason: string },
  ): Promise<DormitoryAbsenceResult> {
    return apiFetch<DormitoryAbsenceResult>(
      `${BASE}/students/${studentId}/absences/${absenceId}/corrections`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  /**
   * Withdraw an absence. The record stays; it stops counting towards the
   * accumulated points and the date becomes free again.
   */
  async cancel(
    studentId: string,
    absenceId: string,
    body: { reason: string },
  ): Promise<DormitoryAbsenceResult> {
    return apiFetch<DormitoryAbsenceResult>(
      `${BASE}/students/${studentId}/absences/${absenceId}/cancellations`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  async me(): Promise<DormitoryStudentDetail> {
    return apiFetch<DormitoryStudentDetail>(`${BASE}/me`);
  },
};
