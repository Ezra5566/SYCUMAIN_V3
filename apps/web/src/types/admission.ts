/** Migration verification types for the Phase 2 staff console. */

export type AdmissionVerificationStatus =
  | "UNVERIFIED"
  | "VERIFIED"
  | "DISPUTED"
  | "REVOKED";

export type ConfirmationSlot = "MANAGEMENT" | "ADMIN";

export type ConfirmationState = "NONE" | "CONFIRMED" | "REVOKED";

export type EvidenceType =
  | "ADMISSION_LETTER"
  | "ENROLMENT_RECORD"
  | "REGISTER_EXTRACT"
  | "OTHER";

export interface MigrationQueueItem {
  admission_id: string;
  student_id: string;
  student_number: string;
  student_name: string;
  admission_status: string;
  verification_status: AdmissionVerificationStatus;
  admission_intake_id: string;
  admission_intake_code: string | null;
  admission_intake_name: string | null;
  admission_intake_start_date: string | null;
  admitted_program_id: string | null;
  admitted_program_name: string | null;
  admitted_program_offering_id: string;
  admitted_program_offering_name: string | null;
  management_confirmation_state: ConfirmationState;
  management_confirmed_by_id: string | null;
  management_confirmed_at: string | null;
  management_revoked_at: string | null;
  admin_confirmation_state: ConfirmationState;
  admin_confirmed_by_id: string | null;
  admin_confirmed_at: string | null;
  admin_revoked_at: string | null;
  outstanding_slots: ConfirmationSlot[];
  original_admission_id: string | null;
  is_original_admission: boolean;
  verified_at: string | null;
  corrections_enabled?: boolean;
  created_at: string;
}

export interface MigrationQueueResponse {
  items: MigrationQueueItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface VerificationAct {
  id: string;
  admission_id: string;
  slot: ConfirmationSlot;
  action: "CONFIRM" | "REVOKE";
  actor_id: string;
  actor_name: string | null;
  acted_at: string;
  candidate_intake_id: string;
  candidate_intake_name: string | null;
  candidate_intake_code: string | null;
  candidate_program_id: string | null;
  candidate_program_name: string | null;
  evidence_type: EvidenceType | null;
  evidence_reference: string | null;
  evidence_note: string | null;
  revocation_reason: string | null;
  resulting_verification_status: AdmissionVerificationStatus | null;
}

export interface ConfirmationInput {
  evidence_type: EvidenceType;
  evidence_reference: string;
  evidence_note?: string;
}
