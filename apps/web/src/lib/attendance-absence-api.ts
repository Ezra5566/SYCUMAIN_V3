/**
 * Student attendance API client (Phase 3).
 *
 * The client never derives a percentage: the server owns the calendar and the
 * commencement, so it also owns the figure. The browser sends an absence and
 * renders what comes back.
 */

import { apiFetch } from "@/lib/api";
import type {
  AbsenceRecordResult,
  MyAttendance,
  StudentAttendanceDetail,
  StudentAttendanceList,
} from "@/types/attendance-absence";

const BASE = "/api/v1/attendance";

export const attendanceApi = {
  async listStudents(params: {
    search?: string;
    periodId?: string;
    page?: number;
    pageSize?: number;
  } = {}): Promise<StudentAttendanceList> {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.periodId) query.set("period_id", params.periodId);
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 25));
    return apiFetch<StudentAttendanceList>(`${BASE}/students?${query.toString()}`);
  },

  async detail(studentId: string): Promise<StudentAttendanceDetail> {
    return apiFetch<StudentAttendanceDetail>(`${BASE}/students/${studentId}`);
  },

  async record(
    studentId: string,
    body: { admission_id: string; absence_date: string; reason: string },
  ): Promise<AbsenceRecordResult> {
    return apiFetch<AbsenceRecordResult>(
      `${BASE}/students/${studentId}/absences`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  async cancel(
    studentId: string,
    absenceId: string,
    body: { reason: string },
  ): Promise<AbsenceRecordResult> {
    return apiFetch<AbsenceRecordResult>(
      `${BASE}/students/${studentId}/absences/${absenceId}/cancellation`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  async correct(
    studentId: string,
    absenceId: string,
    body: { absence_date: string; reason: string },
  ): Promise<AbsenceRecordResult> {
    return apiFetch<AbsenceRecordResult>(
      `${BASE}/students/${studentId}/absences/${absenceId}/corrections`,
      { method: "POST", body: JSON.stringify(body) },
    );
  },

  async me(): Promise<MyAttendance> {
    return apiFetch<MyAttendance>(`${BASE}/me`);
  },
};
