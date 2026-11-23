/** Dormitory attendance types.
 *
 * Separate from the academic attendance types on purpose: this domain has no
 * percentage, no eligible working days and no commencement. It has absences,
 * the housing stay each belongs to, and points.
 */

export type DormitoryIneligibleReason =
  | "NO_HOUSING_ASSIGNMENT"
  | "ASSIGNMENT_NOT_STARTED"
  | "ASSIGNMENT_ENDED"
  | "BETWEEN_ASSIGNMENTS";

export interface DormitoryAssignment {
  id: string;
  building_name: string | null;
  floor_number: number | null;
  room_number: string | null;
  bed_label: string | null;
  bed_number: number | null;
  start_date: string;
  end_date: string | null;
  status: string;
  is_current: boolean;
  absence_count: number;
  points_total: number;
}

export interface DormitoryAbsence {
  id: string;
  student_id: string;
  housing_assignment_id: string;
  absence_date: string;
  points: number;
  reason: string;
  recorded_by_id: string;
  recorded_by_name: string | null;
  recorded_at: string;
  supersedes_id: string | null;
  superseded_at: string | null;
  cancelled_at: string | null;
  cancelled_by_id: string | null;
  cancelled_by_name: string | null;
  cancellation_reason: string | null;
  /** False once the record is superseded or cancelled: it no longer counts. */
  is_active: boolean;
}

export interface DormitoryStudentRow {
  student_id: string;
  student_number: string;
  student_name: string;
  housing_assignment_id: string;
  building_name: string | null;
  floor_number: number | null;
  room_number: string | null;
  bed_label: string | null;
  bed_number: number | null;
  assignment_start_date: string;
  assignment_end_date: string | null;
  assignment_status: string;
  is_current_resident: boolean;
  eligible_today: boolean;
  ineligible_reason: DormitoryIneligibleReason | null;
  absence_count: number;
  points_total: number;
}

export interface DormitoryStudentList {
  items: DormitoryStudentRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface DormitoryStudentDetail {
  student_id: string;
  student_number: string;
  student_name: string;
  has_assignment: boolean;
  is_current_resident: boolean;
  eligible_today: boolean;
  ineligible_reason: DormitoryIneligibleReason | null;
  current_assignment: DormitoryAssignment | null;
  assignments: DormitoryAssignment[];
  absences: DormitoryAbsence[];
  absence_count: number;
  points_total: number;
}

export interface DormitoryAbsenceResult {
  absence: DormitoryAbsence;
  absence_count: number;
  points_total: number;
}
