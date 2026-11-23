/** Examination types.
 *
 * Mirrors the API's two shapes: the staff view (schedules, eligible students,
 * recorded results) and the student view (schedule plus a result that only
 * exists once the institution publishes it).
 */

export type ExaminationStatus = "SCHEDULED" | "CANCELLED";

export type ExaminationType =
  | "ASSIGNMENT"
  | "QUIZ"
  | "MIDTERM"
  | "FINAL"
  | "PROJECT"
  | "OTHER";

export interface ExaminationSection {
  class_section_id: string;
  section_code: string | null;
  label: string;
  course_code: string | null;
  course_name: string | null;
  academic_period_name: string | null;
  /** Programme offerings this section serves; a shared section may serve several. */
  offerings: string[];
  eligible_count: number;
}

export interface Examination {
  id: string;
  title: string;
  examination_type: ExaminationType;
  course_id: string;
  course_code: string | null;
  course_name: string | null;
  academic_period_id: string;
  academic_period_name: string | null;
  program_offering_id: string | null;
  program_offering_name: string | null;
  exam_date: string;
  start_time: string;
  end_time: string;
  location: string | null;
  instructions: string | null;
  max_score: number | null;
  status: ExaminationStatus;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  published_at: string | null;
  published_by_name: string | null;
  sections: ExaminationSection[];
  section_count: number;
  eligible_count: number;
  result_count: number;
  created_at: string;
}

export interface ExaminationList {
  items: Examination[];
  total: number;
  page: number;
  page_size: number;
}

export interface EligibleStudent {
  student_id: string;
  student_number: string;
  student_name: string;
  /** Offering of the student's current placement, when one exists. */
  program_offering_name: string | null;
  section_labels: string[];
  has_result: boolean;
}

export interface ExaminationResult {
  id: string;
  examination_id: string;
  student_id: string;
  student_number: string | null;
  student_name: string | null;
  score: number;
  letter_grade: string | null;
  note: string | null;
  recorded_by_id: string;
  recorded_by_name: string | null;
  recorded_at: string;
  supersedes_id: string | null;
  superseded_at: string | null;
  correction_reason: string | null;
  is_current: boolean;
}

export interface ExaminationDetail {
  examination: Examination;
  eligible_students: EligibleStudent[];
  results: ExaminationResult[];
}

export interface StudentResult {
  score: number;
  letter_grade: string | null;
  note: string | null;
  published_at: string;
}

export interface StudentExamination {
  id: string;
  title: string;
  examination_type: ExaminationType;
  course_code: string | null;
  course_name: string | null;
  exam_date: string;
  start_time: string;
  end_time: string;
  location: string | null;
  instructions: string | null;
  status: ExaminationStatus;
  section_labels: string[];
  is_past: boolean;
  results_published: boolean;
  result: StudentResult | null;
}

export interface StudentExaminationList {
  items: StudentExamination[];
  total: number;
  upcoming_count: number;
  past_count: number;
}

export interface ExaminationDashboardCounts {
  total: number;
  upcoming: number;
  completed: number;
  cancelled: number;
  published: number;
  unpublished_results: number;
  eligible_students: number;
  results_recorded: number;
}

export interface ExaminationDashboard {
  counts: ExaminationDashboardCounts;
  upcoming: Examination[];
  recent: Examination[];
  results: StudentExamination[];
}

export interface ExaminationPayload {
  title: string;
  examination_type: ExaminationType;
  course_id: string;
  academic_period_id: string;
  program_offering_id?: string | null;
  exam_date: string;
  start_time: string;
  end_time: string;
  location?: string | null;
  instructions?: string | null;
  max_score?: number | null;
  section_ids: string[];
}
