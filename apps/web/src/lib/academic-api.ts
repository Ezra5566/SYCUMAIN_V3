import { apiFetch } from "@/lib/api";
import type {
  Major,
  Program,
  Course,
  AcademicPeriod,
  AcademicPeriodDateCorrection,
  Classroom,
  ClassSection,
  Enrollment,
  TimetableEntry,
  StudentAcademicOverview,
  TeachableStaff,
  TeacherAssignment,
  AcademicChangeHistory,
  ProgramOffering,
  PaginatedList,
  SourceIntakeList,
} from "@/types/academic";

export async function listMajors(
  page = 1,
  pageSize = 25,
  search?: string
): Promise<PaginatedList<Major>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/majors?${params}`);
}

export async function listPrograms(
  page = 1,
  pageSize = 25,
  search?: string
): Promise<PaginatedList<Program>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/programs?${params}`);
}

export async function listCourses(
  page = 1,
  pageSize = 25,
  search?: string
): Promise<PaginatedList<Course>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/courses?${params}`);
}

export async function listPeriods(
  page = 1,
  pageSize = 25
): Promise<PaginatedList<AcademicPeriod>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return apiFetch(`/api/v1/academics/periods?${params}`);
}

/**
 * The three accepted source intakes, including ones whose academic period is
 * not configured yet. This is a read-only audit catalog, not a period list.
 */
export async function listSourceIntakes(): Promise<SourceIntakeList> {
  return apiFetch("/api/v1/academics/source-intakes");
}

export async function listClassrooms(
  page = 1,
  pageSize = 25,
  search?: string
): Promise<PaginatedList<Classroom>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/classrooms?${params}`);
}

export async function listClassSections(
  page = 1,
  pageSize = 25,
  search?: string,
  periodId?: string,
  programOfferingId?: string,
  courseId?: string
): Promise<PaginatedList<ClassSection>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (search) params.set("search", search);
  if (periodId) params.set("period_id", periodId);
  if (programOfferingId) params.set("program_offering_id", programOfferingId);
  if (courseId) params.set("course_id", courseId);
  return apiFetch(`/api/v1/academics/classes?${params}`);
}

export async function listProgramOfferings(
  periodId?: string,
  search?: string,
  page = 1,
  pageSize = 100
): Promise<PaginatedList<ProgramOffering>> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (periodId) params.set("period_id", periodId);
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/program-offerings?${params}`);
}

export interface ProgramOfferingWithPeriod extends ProgramOffering {
  period_name: string;
}

/** Every offering across intakes, with its period label for assignment UI. */
export async function listAllProgramOfferings(): Promise<ProgramOfferingWithPeriod[]> {
  const periods = await listPeriods(1, 50);
  const groups = await Promise.all(
    periods.items.map(async (period) => {
      const page = await listProgramOfferings(period.id);
      return page.items.map((offering) => ({
        ...offering,
        period_name: period.name,
      }));
    }),
  );
  return groups.flat();
}

export async function getClassSection(id: string): Promise<ClassSection> {
  return apiFetch(`/api/v1/academics/classes/${id}`);
}

export async function listEnrollments(
  classSectionId: string
): Promise<Enrollment[]> {
  return apiFetch(`/api/v1/academics/classes/${classSectionId}/enrollments`);
}

export async function listTimetable(
  periodId?: string,
  classSectionId?: string,
  programOfferingId?: string,
  courseId?: string
): Promise<{ items: TimetableEntry[] }> {
  const params = new URLSearchParams();
  if (periodId) params.set("period_id", periodId);
  if (classSectionId) params.set("class_section_id", classSectionId);
  if (programOfferingId) params.set("program_offering_id", programOfferingId);
  if (courseId) params.set("course_id", courseId);
  return apiFetch(`/api/v1/academics/timetable?${params}`);
}

export async function getStudentAcademic(
  studentId: string,
  periodId?: string
): Promise<StudentAcademicOverview> {
  const params = new URLSearchParams();
  if (periodId) params.set("period_id", periodId);
  const query = params.toString();
  return apiFetch(`/api/v1/academics/students/${studentId}${query ? `?${query}` : ""}`);
}

export async function getStudentTimetable(
  studentId: string,
  periodId?: string
): Promise<{ items: TimetableEntry[] }> {
  const params = new URLSearchParams();
  if (periodId) params.set("period_id", periodId);
  return apiFetch(`/api/v1/academics/students/${studentId}/timetable?${params}`);
}

/** Stage 9A append-only history for assessments and grades in one class. */
export async function getClassRecordHistory(
  classId: string,
  entityType?: "ASSESSMENT" | "GRADE",
): Promise<AcademicChangeHistory[]> {
  const params = new URLSearchParams();
  if (entityType) params.set("entity_type", entityType);
  const query = params.toString();
  return apiFetch(
    `/api/v1/academics/classes/${classId}/record-history${query ? `?${query}` : ""}`,
  );
}

// ── Write operations ──
//
// These mirror the API's create/update schemas field for field. The payload
// types are declared locally rather than reusing the read models, because a
// create body is genuinely a different shape: `code` is required and absent
// from an update, `major_name` is server-composed and never sent back.

export interface MajorInput {
  code?: string;
  name?: string;
  description?: string | null;
  status?: "ACTIVE" | "INACTIVE";
}

export async function createMajor(input: MajorInput): Promise<Major> {
  return apiFetch("/api/v1/academics/majors", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateMajor(
  id: string,
  input: MajorInput
): Promise<Major> {
  return apiFetch(`/api/v1/academics/majors/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export interface ProgramInput {
  major_id?: string;
  code?: string;
  name?: string;
  description?: string | null;
  duration_years?: number | null;
  status?: "ACTIVE" | "INACTIVE";
}

export async function createProgram(input: ProgramInput): Promise<Program> {
  return apiFetch("/api/v1/academics/programs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateProgram(
  id: string,
  input: ProgramInput
): Promise<Program> {
  return apiFetch(`/api/v1/academics/programs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export interface CourseInput {
  program_id?: string | null;
  code?: string | null;
  name?: string;
  name_zh?: string | null;
  description?: string | null;
  credits?: number | null;
  semester?: number | null;
  status?: "ACTIVE" | "INACTIVE";
}

export async function createCourse(input: CourseInput): Promise<Course> {
  return apiFetch("/api/v1/academics/courses", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateCourse(
  id: string,
  input: CourseInput
): Promise<Course> {
  return apiFetch(`/api/v1/academics/courses/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export interface PeriodInput {
  name?: string;
  code?: string;
  start_date?: string;
  end_date?: string;
  status?: "PLANNED" | "ACTIVE" | "COMPLETED" | "CANCELLED";
}

export async function createPeriod(
  input: PeriodInput
): Promise<AcademicPeriod> {
  return apiFetch("/api/v1/academics/periods", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updatePeriod(
  id: string,
  input: PeriodInput
): Promise<AcademicPeriod> {
  return apiFetch(`/api/v1/academics/periods/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export interface PeriodDateCorrectionInput {
  new_start_date: string;
  new_end_date: string;
  reason: string;
  evidence_reference?: string | null;
}

/** Correction history is append-only; a reversal is another POST. */
export async function listPeriodDateCorrections(
  id: string
): Promise<AcademicPeriodDateCorrection[]> {
  return apiFetch(`/api/v1/academics/periods/${id}/date-corrections`);
}

export async function correctPeriodDates(
  id: string,
  input: PeriodDateCorrectionInput
): Promise<AcademicPeriodDateCorrection> {
  return apiFetch(`/api/v1/academics/periods/${id}/date-correction`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export interface ClassroomInput {
  building?: string | null;
  campus?: string | null;
  room_code?: string;
  name?: string | null;
  capacity?: number | null;
  status?: "AVAILABLE" | "UNAVAILABLE" | "MAINTENANCE";
}

export async function createClassroom(
  input: ClassroomInput
): Promise<Classroom> {
  return apiFetch("/api/v1/academics/classrooms", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateClassroom(
  id: string,
  input: ClassroomInput
): Promise<Classroom> {
  return apiFetch(`/api/v1/academics/classrooms/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export interface ProgramOfferingInput {
  academic_period_id?: string;
  source_id?: string;
  name?: string;
  name_zh?: string | null;
  program_id?: string | null;
}

export async function createProgramOffering(
  input: ProgramOfferingInput
): Promise<ProgramOffering> {
  return apiFetch("/api/v1/academics/program-offerings", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateProgramOffering(
  id: string,
  input: ProgramOfferingInput
): Promise<ProgramOffering> {
  return apiFetch(`/api/v1/academics/program-offerings/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function setClassSectionProgramOfferings(
  id: string,
  programOfferingIds: string[]
): Promise<ClassSection> {
  return apiFetch(`/api/v1/academics/classes/${id}/program-offerings`, {
    method: "PUT",
    body: JSON.stringify({ program_offering_ids: programOfferingIds }),
  });
}

export interface ClassSectionInput {
  course_id?: string;
  academic_period_id?: string;
  section_code?: string | null;
  source_label?: string | null;
  capacity?: number | null;
  status?: "PLANNED" | "ACTIVE" | "COMPLETED" | "CANCELLED";
}

export async function createClassSection(
  input: ClassSectionInput
): Promise<ClassSection> {
  return apiFetch("/api/v1/academics/classes", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateClassSection(
  id: string,
  input: ClassSectionInput
): Promise<ClassSection> {
  return apiFetch(`/api/v1/academics/classes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

/** Staff eligible for assignment. The picker needs real people, not UUIDs. */
export async function listTeachableStaff(
  search?: string
): Promise<{ items: TeachableStaff[]; total: number }> {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  return apiFetch(`/api/v1/academics/teachers?${params}`);
}

export async function listClassTeachers(
  classId: string
): Promise<TeacherAssignment[]> {
  return apiFetch(`/api/v1/academics/classes/${classId}/teachers`);
}

export async function assignTeacher(
  classId: string,
  input: { staff_id: string; role?: "PRIMARY" | "ASSISTANT" }
): Promise<TeacherAssignment> {
  return apiFetch(`/api/v1/academics/classes/${classId}/teachers`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function removeTeacher(
  classId: string,
  assignmentId: string
): Promise<void> {
  return apiFetch(
    `/api/v1/academics/classes/${classId}/teachers/${assignmentId}`,
    { method: "DELETE" }
  );
}

/**
 * Enroll a student.
 *
 * The API takes an internal student id only (`EnrollmentCreate.student_id` is a
 * UUID), so the enrollment UI resolves what a clerk types through the student
 * directory search and passes the id it returns.
 */
export async function enrollStudent(
  classId: string,
  studentId: string
): Promise<Enrollment> {
  return apiFetch(`/api/v1/academics/classes/${classId}/enrollments`, {
    method: "POST",
    body: JSON.stringify({ student_id: studentId }),
  });
}

export async function dropEnrollment(
  classId: string,
  enrollmentId: string
): Promise<Enrollment> {
  return apiFetch(
    `/api/v1/academics/classes/${classId}/enrollments/${enrollmentId}/drop`,
    { method: "POST" }
  );
}

export interface TimetableInput {
  class_section_id?: string;
  classroom_id?: string | null;
  day_of_week?: number;
  start_time?: string;
  end_time?: string;
}

export async function createTimetableEntry(
  input: TimetableInput
): Promise<TimetableEntry> {
  return apiFetch("/api/v1/academics/timetable", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateTimetableEntry(
  id: string,
  input: TimetableInput
): Promise<TimetableEntry> {
  return apiFetch(`/api/v1/academics/timetable/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteTimetableEntry(id: string): Promise<void> {
  return apiFetch(`/api/v1/academics/timetable/${id}`, { method: "DELETE" });
}
