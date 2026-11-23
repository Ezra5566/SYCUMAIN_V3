/** Controlled changes inside one admission episode (Phase 4). */

export type AdmissionChangeType =
  | "PROGRAM_CHANGE"
  | "PLACEMENT_CHANGE"
  | "EARLIER_INTAKE_PLACEMENT"
  | "WITHDRAWAL"
  | "STATUS_CORRECTION";

export type AdmissionChangeStatus = "PENDING" | "APPROVED" | "REJECTED" | "CANCELLED";

export interface AdmissionChange {
  id: string;
  admission_id: string;
  student_id: string;
  change_type: AdmissionChangeType;
  status: AdmissionChangeStatus;
  from_program_id: string | null;
  from_program_name: string | null;
  to_program_id: string | null;
  to_program_name: string | null;
  from_program_offering_id: string | null;
  from_program_offering_name: string | null;
  to_program_offering_id: string | null;
  to_program_offering_name: string | null;
  target_period_id: string | null;
  target_period_name: string | null;
  proposed_data: Record<string, unknown>;
  current_data_snapshot: Record<string, unknown> | null;
  reason: string | null;
  requested_by_id: string;
  requested_by_name: string | null;
  requested_at: string;
  reviewed_by_id: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  decision_reason: string | null;
}

export interface AdmissionChangeListResponse {
  items: AdmissionChange[];
  total: number;
}

export interface AdmissionChangeInput {
  change_type: AdmissionChangeType;
  to_program_id?: string;
  to_program_offering_id?: string;
  target_period_id?: string;
  proposed_data?: Record<string, unknown>;
  reason?: string;
}

export interface AdmissionChangeReviewInput {
  decision: "APPROVE" | "REJECT";
  reason?: string;
}
