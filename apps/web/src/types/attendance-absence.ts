/** Student attendance and absence types (Phase 3, corrected model). */

export type IneligibleReason =
  | "NO_ACTIVE_ADMISSION"
  | "NO_COMMENCEMENT"
  | "NOT_STARTED";

export interface Absence {
  id: string;
  student_id: string;
  admission_id: string;
  absence_date: string;
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
}

export interface AttendanceCalculation {
  commencement_date: string | null;
  window_start: string | null;
  window_end: string | null;
  calculation_date: string;
  eligible_days: number;
  absence_count: number;
  excluded_absence_count: number;
  percentage: number | null;
}

export interface StudentAttendanceRow {
  student_id: string;
  student_number: string;
  student_name: string;
  admission_id: string;
  admission_status: string;
  period_id: string;
  period_name: string;
  commencement_date: string | null;
  eligible: boolean;
  ineligible_reason: IneligibleReason | null;
  eligible_days: number;
  absence_count: number;
  excluded_absence_count: number;
  percentage: number | null;
}

export interface StudentAttendanceList {
  items: StudentAttendanceRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface StudentAttendanceDetail extends StudentAttendanceRow {
  absences: Absence[];
}

export interface EpisodeAttendance {
  admission_id: string;
  admission_status: string;
  period_name: string;
  commencement_date: string | null;
  eligible: boolean;
  eligible_days: number;
  absence_count: number;
  excluded_absence_count: number;
  percentage: number | null;
  absences: Absence[];
}

export interface MyAttendance {
  student_id: string;
  student_number: string;
  student_name: string;
  episodes: EpisodeAttendance[];
}

export interface AbsenceRecordResult {
  absence: Absence;
  calculation: AttendanceCalculation;
}
