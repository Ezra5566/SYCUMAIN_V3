/** Attendance commencement types (Phase 2). Mirrors the API contract exactly. */

export type CommencementType = "SCHEDULED" | "LATE_JOIN" | "MANUAL";

export type CommencementStatusFilter = "MISSING" | "RECORDED" | "ALL";

export type SuggestionBasis = "INTAKE_START" | "ACTIVATION";

export interface CommencementRecord {
  id: string;
  admission_id: string;
  student_id: string;
  commencement_date: string;
  commencement_type: CommencementType;
  reason: string;
  suggested_date: string;
  supersedes_id: string | null;
  superseded_at: string | null;
  approved_by_id: string;
  approved_by_name: string | null;
  approved_at: string;
  created_at: string;
}

export interface CommencementSummary {
  admission_id: string;
  student_id: string;
  student_name: string;
  student_number: string;
  admission_status: string;
  intake_id: string;
  intake_name: string;
  intake_start_date: string;
  activated_on: string | null;
  suggested_date: string;
  suggestion_basis: SuggestionBasis;
  current: CommencementRecord | null;
  history: CommencementRecord[];
}

export interface CommencementListResponse {
  items: CommencementSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface CommencementInput {
  commencement_date: string;
  commencement_type: CommencementType;
  reason: string;
  confirmed_suggested_date: string;
}
