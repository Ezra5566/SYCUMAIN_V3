import { apiFetch } from "@/lib/api";
import type {
  AdmissionChange,
  AdmissionChangeInput,
  AdmissionChangeListResponse,
  AdmissionChangeReviewInput,
} from "@/types/admission-change";

class AdmissionChangeApiClient {
  async list(studentId: string): Promise<AdmissionChangeListResponse> {
    return apiFetch(`/api/v1/students/${studentId}/admission-changes`);
  }

  async listOwn(): Promise<AdmissionChangeListResponse> {
    return apiFetch("/api/v1/students/me/admission-changes");
  }

  async request(
    studentId: string,
    admissionId: string,
    input: AdmissionChangeInput,
  ): Promise<AdmissionChange> {
    return apiFetch(
      `/api/v1/students/${studentId}/admissions/${admissionId}/changes`,
      { method: "POST", body: JSON.stringify(input) },
    );
  }

  async requestOwn(input: AdmissionChangeInput): Promise<AdmissionChange> {
    return apiFetch("/api/v1/students/me/admission-changes", {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async review(
    changeId: string,
    input: AdmissionChangeReviewInput,
  ): Promise<AdmissionChange> {
    return apiFetch(`/api/v1/academic/admission-changes/${changeId}/review`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }
}

export const admissionChangeApi = new AdmissionChangeApiClient();
