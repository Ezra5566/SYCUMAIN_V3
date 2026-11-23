/**
 * Student API client for communicating with the FastAPI backend.
 *
 * Uses the shared `apiFetch` helper so every client has identical cookie,
 * header, and error behaviour (see lib/api.ts and lib/api-error.ts).
 */

import { API_BASE, apiFetch } from "@/lib/api";
import { apiErrorFromResponse } from "@/lib/api-error";
import type {
  ImmigrationStatusFilter,
  StudentAccount,
  StudentBulkResponse,
  StudentCreate,
  StudentDetail,
  StudentImportReport,
  StudentListResponse,
  StudentOnboard,
  StudentOnboardedResponse,
  StudentSelfUpdate,
  StudentSort,
  StudentStatus,
  StudentUpdate,
} from "@/types/student";

class StudentApiClient {
  private request<T>(path: string, options: RequestInit = {}): Promise<T> {
    return apiFetch<T>(path, options);
  }

  /** List students with pagination, search, and filtering */
  async listStudents(params: {
    page?: number;
    page_size?: number;
    search?: string;
    status?: StudentStatus;
    major_id?: string;
    program_id?: string;
    has_housing?: boolean;
    immigration_status?: ImmigrationStatusFilter;
    original_intake_id?: string;
    current_intake_id?: string;
    sort?: StudentSort;
  } = {}): Promise<StudentListResponse> {
    const searchParams = new URLSearchParams();
    if (params.page) searchParams.set("page", params.page.toString());
    if (params.page_size)
      searchParams.set("page_size", params.page_size.toString());
    if (params.search) searchParams.set("search", params.search);
    if (params.status) searchParams.set("status", params.status);
    if (params.major_id) searchParams.set("major_id", params.major_id);
    if (params.program_id) searchParams.set("program_id", params.program_id);
    if (params.has_housing !== undefined)
      searchParams.set("has_housing", String(params.has_housing));
    if (params.immigration_status)
      searchParams.set("immigration_status", params.immigration_status);
    if (params.original_intake_id)
      searchParams.set("original_intake_id", params.original_intake_id);
    if (params.current_intake_id)
      searchParams.set("current_intake_id", params.current_intake_id);
    if (params.sort) searchParams.set("sort", params.sort);

    const queryString = searchParams.toString();
    const path = `/api/v1/students/${queryString ? `?${queryString}` : ""}`;

    return this.request<StudentListResponse>(path);
  }

  /** Get a student's detailed profile */
  async getStudent(studentId: string): Promise<StudentDetail> {
    return this.request<StudentDetail>(`/api/v1/students/${studentId}`);
  }

  /**
   * Get the caller's own student record.
   *
   * Resolved from the session, so a student never needs to know — or guess —
   * a record identifier to reach their own profile.
   */
  async getMyStudent(): Promise<StudentDetail> {
    return this.request<StudentDetail>("/api/v1/students/me");
  }

  /** Create a new student */
  async createStudent(data: StudentCreate): Promise<StudentDetail> {
    return this.request<StudentDetail>("/api/v1/students/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /** Update a student */
  async updateStudent(
    studentId: string,
    data: StudentUpdate
  ): Promise<StudentDetail> {
    return this.request<StudentDetail>(`/api/v1/students/${studentId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  /** Archive a student */
  async archiveStudent(studentId: string): Promise<StudentDetail> {
    return this.request<StudentDetail>(
      `/api/v1/students/${studentId}/archive`,
      {
        method: "POST",
      }
    );
  }

  /** Change a student's enrolment status */
  async setStatus(
    studentId: string,
    status: StudentStatus,
  ): Promise<StudentDetail> {
    return this.request<StudentDetail>(`/api/v1/students/${studentId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  }

  /**
   * Create a student together with their login account.
   *
   * The response includes a one-time temporary password to hand to the student.
   */
  async onboardStudent(data: StudentOnboard): Promise<StudentOnboardedResponse> {
    return this.request<StudentOnboardedResponse>("/api/v1/students/onboard", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /** Read the login account linked to a student */
  async getStudentAccount(studentId: string): Promise<StudentAccount> {
    return this.request<StudentAccount>(`/api/v1/students/${studentId}/account`);
  }

  /**
   * Update the fields a student may maintain themselves.
   *
   * The backend allowlists these fields, so administrative values sent from
   * the browser are ignored rather than trusted.
   */
  async updateSelf(
    studentId: string,
    data: StudentSelfUpdate,
  ): Promise<StudentDetail> {
    return this.request<StudentDetail>(`/api/v1/students/${studentId}/self`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  /** Apply one status change to many students */
  async bulkSetStatus(
    studentIds: string[],
    status: StudentStatus,
  ): Promise<StudentBulkResponse> {
    return this.request<StudentBulkResponse>("/api/v1/students/bulk/status", {
      method: "POST",
      body: JSON.stringify({ student_ids: studentIds, status }),
    });
  }

  /**
   * Upload or replace a profile photo.
   *
   * `PUT`, not `POST`: the endpoint is idempotent by design — there is at most
   * one photo on a record, so replacing it is a write of the same resource
   * rather than the creation of a new one.
   *
   * `Content-Type` is deliberately absent: the browser must generate the
   * multipart boundary, and the backend validates the real image type from the
   * bytes rather than from the filename or the declared type.
   */
  async uploadPhoto(studentId: string, file: File): Promise<StudentDetail> {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(
      `${API_BASE}/api/v1/students/${studentId}/photo`,
      { method: "PUT", credentials: "include", body: form },
    );
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.json() as Promise<StudentDetail>;
  }

  /** Remove a profile photo. */
  async removePhoto(studentId: string): Promise<StudentDetail> {
    return this.request<StudentDetail>(`/api/v1/students/${studentId}/photo`, {
      method: "DELETE",
    });
  }

  /**
   * Fetch the photo bytes for an authorized viewer.
   *
   * Fetched rather than used as an `<img src>` so the session cookie is sent
   * and a refusal surfaces as an error. The API serves no URL — the photo is
   * exactly as private as the record it belongs to — so the caller owns the
   * object URL and must revoke it.
   */
  async fetchPhoto(studentId: string): Promise<Blob | null> {
    const response = await fetch(
      `${API_BASE}/api/v1/students/${studentId}/photo`,
      { credentials: "include" },
    );
    // "No photo on file" is an ordinary state, not a failure to report.
    if (response.status === 404) return null;
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.blob();
  }

  /** Whether the signed-in student may still choose their own placement. */
  async getOwnPlacement(): Promise<{
    can_select: boolean;
    major_id: string | null;
    major_name: string | null;
    program_id: string | null;
    program_name: string | null;
    program_offering_id: string | null;
    program_offering_name: string | null;
    program_offering_period_id: string | null;
    program_offering_period_name: string | null;
  }> {
    return this.request("/api/v1/students/me/academic");
  }

  /**
   * Validate or apply a CSV intake file.
   *
   * `dry_run` is the default stance of the UI: an operator sees exactly what
   * would happen before anything is written.
   */
  async importStudents(
    file: File,
    options: { dryRun?: boolean; skipInvalid?: boolean } = {},
  ): Promise<StudentImportReport> {
    const form = new FormData();
    form.append("file", file);

    const params = new URLSearchParams();
    if (options.dryRun) params.set("dry_run", "true");
    if (options.skipInvalid) params.set("skip_invalid", "true");

    // No `Content-Type`: the browser must set the multipart boundary itself.
    const response = await fetch(
      `${API_BASE}/api/v1/students/import?${params.toString()}`,
      { method: "POST", credentials: "include", body: form },
    );
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.json() as Promise<StudentImportReport>;
  }

  /** Download the exact header the importer expects. */
  async importTemplate(): Promise<Blob> {
    const response = await fetch(
      `${API_BASE}/api/v1/students/import/template`,
      { credentials: "include" },
    );
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.blob();
  }

  /** Download the student directory as CSV (management only). */
  async exportDirectory(): Promise<Blob> {
    const response = await fetch(`${API_BASE}/api/v1/students/export`, {
      credentials: "include",
    });
    if (!response.ok) throw await apiErrorFromResponse(response);
    return response.blob();
  }

  /**
   * A student declares their major and programme.
   *
   * Accepted only while no placement has been confirmed; afterwards the API
   * refuses and the change must go through the international office.
   */
  async selectOwnPlacement(input: {
    major_id?: string | null;
    program_id?: string | null;
    program_offering_id: string;
  }): Promise<StudentDetail> {
    return this.request<StudentDetail>("/api/v1/students/me/academic", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }
}

export const studentApi = new StudentApiClient();
