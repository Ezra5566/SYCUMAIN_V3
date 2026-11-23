/**
 * Admission migration verification API client.
 *
 * Every mutation is the existing Phase 2 backend endpoint. The frontend never
 * computes trust states, fills slots locally, or decides who may confirm: it
 * only presents the controls the current permissions allow.
 */

import { apiFetch } from "@/lib/api";
import type {
  AdmissionVerificationStatus,
  ConfirmationInput,
} from "@/types/admission";
import type {
  MigrationQueueResponse,
  VerificationAct,
} from "@/types/admission";
import type { AdmissionForPlacement } from "@/types/placement";

class AdmissionApiClient {
  async admissions(studentId: string): Promise<AdmissionForPlacement[]> {
    const result = await apiFetch<{ items: AdmissionForPlacement[] }>(
      `/api/v1/students/${studentId}/admissions`,
    );
    return result.items;
  }

  async ownAdmissions(): Promise<AdmissionForPlacement[]> {
    const result = await apiFetch<{ items: AdmissionForPlacement[] }>(
      "/api/v1/students/me/admission-episodes",
    );
    return result.items;
  }

  async queue(params: {
    verification_status?: AdmissionVerificationStatus;
    search?: string;
    page?: number;
    page_size?: number;
  } = {}): Promise<MigrationQueueResponse> {
    const searchParams = new URLSearchParams();
    if (params.verification_status) {
      searchParams.set("verification_status", params.verification_status);
    }
    if (params.search) searchParams.set("search", params.search);
    if (params.page) searchParams.set("page", String(params.page));
    if (params.page_size) searchParams.set("page_size", String(params.page_size));
    const query = searchParams.toString();
    return apiFetch<MigrationQueueResponse>(
      `/api/v1/admission-verification/queue${query ? `?${query}` : ""}`,
    );
  }

  async createCandidate(
    studentId: string,
    input: { admission_intake_id: string; program_offering_id: string },
  ): Promise<void> {
    await apiFetch(`/api/v1/students/${studentId}/admissions/migrated`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async updateCandidate(
    studentId: string,
    admissionId: string,
    input: { admission_intake_id: string; program_offering_id: string },
  ): Promise<void> {
    await apiFetch(
      `/api/v1/students/${studentId}/admissions/${admissionId}/migrated`,
      { method: "PATCH", body: JSON.stringify(input) },
    );
  }

  async acts(studentId: string, admissionId: string): Promise<VerificationAct[]> {
    return apiFetch<VerificationAct[]>(
      `/api/v1/students/${studentId}/admissions/${admissionId}/verification-acts`,
    );
  }

  async confirm(
    studentId: string,
    admissionId: string,
    slot: "MANAGEMENT" | "ADMIN",
    input: ConfirmationInput,
  ): Promise<void> {
    await apiFetch(
      `/api/v1/students/${studentId}/admissions/${admissionId}/confirm/${slot}`,
      { method: "POST", body: JSON.stringify(input) },
    );
  }

  async revoke(
    studentId: string,
    admissionId: string,
    slot: "MANAGEMENT" | "ADMIN",
    reason: string,
  ): Promise<void> {
    await apiFetch(
      `/api/v1/students/${studentId}/admissions/${admissionId}/confirm/${slot}/revoke`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
  }

  async correctPointer(
    studentId: string,
    admissionId: string,
    reason: string,
    evidenceReference: string,
  ): Promise<void> {
    await apiFetch(
      `/api/v1/students/${studentId}/original-admission/correction`,
      {
        method: "POST",
        body: JSON.stringify({
          new_admission_id: admissionId,
          reason,
          evidence_reference: evidenceReference || null,
        }),
      },
    );
  }

  async correctStatus(
    studentId: string,
    admissionId: string,
    targetStatus: string,
    reason: string,
  ): Promise<AdmissionForPlacement> {
    return apiFetch<AdmissionForPlacement>(
      `/api/v1/students/${studentId}/admissions/${admissionId}/corrections/status`,
      {
        method: "POST",
        body: JSON.stringify({ target_status: targetStatus, reason }),
      },
    );
  }
}

export const admissionApi = new AdmissionApiClient();
