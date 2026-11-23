/** Current academic placement and its append-only history. */

export interface Placement {
  id: string;
  student_id: string;
  admission_id: string;

  admission_intake_id: string;
  admission_intake_code: string | null;
  admission_intake_name: string | null;
  admission_intake_start_date: string | null;

  placement_intake_id: string;
  placement_intake_code: string | null;
  placement_intake_name: string | null;
  placement_intake_start_date: string | null;

  program_id: string | null;
  program_name: string | null;
  program_offering_id: string;
  program_offering_name: string | null;

  is_earlier_intake_placement: boolean;
  authorized_by_id: string | null;
  authorized_by_name: string | null;
  authorization_reason: string | null;
  effective_from: string;
  ended_at: string | null;
  is_current: boolean;
  created_by_id: string;
  created_by_name: string | null;
  created_at: string;
}

export interface PlacementListResponse {
  items: Placement[];
  total: number;
}

export interface PlacementInput {
  admission_id: string;
  program_offering_id: string;
  effective_from?: string;
  reason?: string;
}

/** The admission fields the placement panel needs to label the original record. */
export interface AdmissionForPlacement {
  id: string;
  status: string;
  corrections_enabled?: boolean;
  admission_intake_id: string;
  admission_intake_name: string | null;
  admission_intake_code: string | null;
  admission_intake_start_date: string | null;
  admitted_program_id: string | null;
  admitted_program_name: string | null;
  admitted_program_offering_id: string;
  admitted_program_offering_name: string | null;
  current_program_id: string | null;
  current_program_name: string | null;
  activated_at?: string | null;
  ended_at?: string | null;
  end_reason?: string | null;
}
