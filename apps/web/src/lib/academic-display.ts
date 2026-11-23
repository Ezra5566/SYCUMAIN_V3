/** Human labels for records whose official codes may be absent in imports. */

interface SectionLabelSource {
  course_code?: string | null;
  course_name?: string | null;
  section_code?: string | null;
  source_label?: string | null;
}

export function courseLabel(course: {
  code?: string | null;
  name?: string | null;
}): string {
  return course.code ?? course.name ?? "—";
}

/**
 * A section may have no official code. Fall back to the source description,
 * then to the course name, and never render the literal string "null".
 */
export function sectionLabel(section: SectionLabelSource): string {
  const course = section.course_code ?? section.course_name ?? "—";
  const group = section.section_code ?? section.source_label;
  if (!group) return course;
  // Imported source labels often repeat the course name and then describe the
  // cohort. Showing "Course · Course [cohort]" reads as a data error.
  if (group === course || group.startsWith(`${course} [`)) return group;
  return `${course} · ${group}`;
}

/** A compact label for a timetable cell; cohort lists belong in the editor. */
export function timetableLabel(entry: SectionLabelSource): string {
  const course = entry.course_code ?? entry.course_name ?? "—";
  return entry.section_code ? `${course} · ${entry.section_code}` : course;
}
