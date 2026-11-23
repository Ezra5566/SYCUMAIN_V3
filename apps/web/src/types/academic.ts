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
