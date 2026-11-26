import type { components } from "./generated/api";

/**
 * Academic types — generated from the backend OpenAPI document.
 *
 * `StudentAcademicOverview` is composed here rather than aliased: the endpoint
 * returns a per-student view that is not a reusable schema in the document.
 */

type Schemas = components["schemas"];

export type Major = Schemas["MajorResponse"];
export type Program = Schemas["ProgramResponse"];
export type Course = Schemas["CourseResponse"];
export type AcademicPeriod = Schemas["AcademicPeriodResponse"];
export type AcademicPeriodDateCorrection =
  Schemas["AcademicPeriodDateCorrectionResponse"];
export type Classroom = Schemas["ClassroomResponse"];

export type ProgramOffering = Schemas["ProgramOfferingResponse"];
export type ProgramOfferingSummary = Schemas["ProgramOfferingSummary"];

export type SourceIntakeList = Schemas["SourceIntakeListResponse"];
export type SourceIntake = Schemas["SourceIntakeResponse"];
export type SourceIntakeOffering = Schemas["SourceIntakeOfferingResponse"];
export type SourceIntakeSection = Schemas["SourceIntakeSectionResponse"];
export type SourceIntakeSubject = Schemas["SourceIntakeSubjectResponse"];

export type TeacherInfo = Schemas["TeacherInfo"];

export type ClassSection = Schemas["ClassSectionResponse"];

/** A staff member who can be assigned to a class section. */
export type TeachableStaff = Schemas["TeachableStaff"];

/** A teacher attached to a class section, as returned by the assign endpoint. */
export type TeacherAssignment = Schemas["TeacherAssignmentResponse"];

/** Stage 9A audit row for an assessment or grade change. */
export type AcademicChangeHistory = Schemas["AcademicChangeHistoryResponse"];

export type Enrollment = Schemas["EnrollmentResponse"];

export type TimetableEntry = Schemas["TimetableEntryResponse"];

export type AttendanceRecord = Schemas["AttendanceRecordResponse"];

export type Assessment = Schemas["AssessmentResponse"];

export type Grade = Schemas["GradeResponse"];

export interface StudentAcademicOverview {
  student_id: string;
  student_name: string;
  major: Major | null;
  program: Program | null;
  program_offering: ProgramOfferingSummary | null;
  current_period: AcademicPeriod | null;
  selected_period: AcademicPeriod | null;
  is_current: boolean;
  enrolled_classes: {
    id: string;
    course_code: string | null;
    course_name: string | null;
    section_code: string | null;
    source_label?: string | null;
    academic_period_name: string | null;
    enrolled_count: number;
    capacity: number | null;
    status: string;
    program_offerings?: ProgramOfferingSummary[];
  }[];
  timetable: TimetableEntry[];
}

/**
 * Shared institutional timetable.
 *
 * Hand-written because the generated document predates these endpoints. They
 * mirror `InstitutionalTimetableResponse` in the API schemas exactly; the
 * distinction that matters is that this response never depends on the
 * viewer's enrolments.
 */
export interface InstitutionalTimetableIssue {
  code: string;
  count: number;
}

export interface InstitutionalTimetableReadiness {
  status: "COMPLETE" | "INCOMPLETE";
  message_code: string | null;
  courses_total: number;
  courses_scheduled: number;
  sessions: number;
  sections_total: number;
  sections_scheduled: number;
  issues: InstitutionalTimetableIssue[];
}

export interface InstitutionalTimetableSection {
  id: string;
  course_code: string | null;
  course_name: string | null;
  section_code: string | null;
  source_label: string | null;
  teachers: string[];
  session_count: number;
}

export interface InstitutionalTimetableResponse {
  period: AcademicPeriod;
  program_offering: ProgramOfferingSummary;
  offerings: ProgramOfferingSummary[];
  sections: InstitutionalTimetableSection[];
  entries: TimetableEntry[];
  readiness: InstitutionalTimetableReadiness;
}

/** Staged source-catalogue import, as reported by `/academics/imports`. */
export interface AcademicImportRowReport {
  entity_type: string;
  action: string;
  source_key: string;
  error_code: string | null;
  target_id: string | null;
}

export interface AcademicImportPeriodOption {
  source_id: string;
  source_key: string;
  mapped_period_id: string | null;
  mapped_period_code: string | null;
}

export interface AcademicImportBatchReport {
  batch_id: string;
  status: string;
  dry_run: boolean;
  source_name: string;
  source_sha256: string;
  created_at: string;
  finished_at: string | null;
  counts: Record<string, number>;
  periods: AcademicImportPeriodOption[];
  by_entity: Record<string, number>;
  by_action: Record<string, number>;
  held: AcademicImportRowReport[];
  already_applied: boolean;
}

/** Timetable reconciliation report (staff diagnostics). */
export interface TimetableReconciliationFinding {
  code: string;
  count: number;
  items_truncated: boolean;
  items: {
    code: string;
    severity: string;
    entity_type: string;
    entity_id: string;
    suggested_action: string | null;
    detail: Record<string, unknown>;
  }[];
}

export interface TimetableReconciliation {
  generated_at: string;
  scope: { period_ids: string[]; period_codes: string[] };
  totals: {
    periods: number;
    sections: number;
    live_entries: number;
    retired_entries: number;
    findings: number;
    blocking: number;
    warnings: number;
  };
  status: string;
  findings: TimetableReconciliationFinding[];
}

/** Generic paginated list used by list endpoints. */
export interface PaginatedList<T> {
  items: T[];
  meta: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}
