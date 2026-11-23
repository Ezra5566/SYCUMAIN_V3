"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Settings2 } from "lucide-react";
import {
  createClassroom,
  createClassSection,
  createCourse,
  createMajor,
  createPeriod,
  createProgram,
  createProgramOffering,
  setClassSectionProgramOfferings,
  updateClassroom,
  updateClassSection,
  updateCourse,
  updateMajor,
  updatePeriod,
  updateProgram,
  updateProgramOffering,
} from "@/lib/academic-api";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import {
  EntityFormDialog,
  toPayload,
  type FieldSpec,
  type FieldValues,
} from "@/components/academics/entity-form";
import type {
  AcademicPeriod,
  Classroom,
  ClassSection,
  Course,
  Major,
  Program,
  ProgramOffering,
} from "@/types/academic";

/**
 * Create/edit dialogs for each academic structure entity.
 *
 * Every one of these follows the same shape, so the field lists below are the
 * whole specification of what management can change. Three rules are shared:
 *
 *   - An update never sends a field the dialog did not render. The API treats
 *     an absent key as "leave alone", so a narrow edit form cannot silently
 *     blank the columns it does not show.
 *   - `code` is absent from every update. A code is the identifier other
 *     records and printed documents already refer to; renaming it is not an
 *     edit, it is a re-identification the API does not offer.
 *   - A create sends only what is required plus what the user filled in, so the
 *     server's defaults apply where the school has not stated a preference.
 */

/** Status options are the API's enum members, labelled for humans. */
function useStatusOptions(
  namespace: string,
  values: string[],
): { value: string; label: string }[] {
  const t = useTranslations(namespace);
  return values.map((value) => ({ value, label: t(value) }));
}

/** Labels assembled from `academics.fields`, shared by every entity below. */
function useFieldLabels() {
  const t = useTranslations("academics.fields");
  return {
    code: t("code"),
    name: t("name"),
    description: t("description"),
    status: t("status"),
    major: t("major"),
    program: t("program"),
    course: t("course"),
    period: t("period"),
    semester: t("semester"),
    startDate: t("startDate"),
    endDate: t("endDate"),
    roomCode: t("roomCode"),
    building: t("building"),
    capacity: t("capacity"),
    sourceId: t("sourceId"),
    nameZh: t("nameZh"),
  };
}

/** Chrome shared by every dialog: title, buttons and save confirmation. */
function useDialogChrome() {
  const t = useTranslations("academics");
  const tCommon = useTranslations("common");
  return {
    t,
    cancelLabel: tCommon("actions.cancel"),
    savingLabel: tCommon("states.saving"),
    submitLabel: tCommon("actions.save"),
    createTitle: (entity: string) =>
      `${tCommon("actions.add")} — ${entity}`,
    editTitle: (entity: string) => `${tCommon("actions.edit")} — ${entity}`,
    triggerLabel: (entity: string) => tCommon("actions.add") + " " + entity,
    description: t("admin.formDescription"),
  };
}

// ── Major ──

export function MajorDialog({
  major,
  onSaved,
}: {
  major?: Major;
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const statuses = useStatusOptions("academics.entityStatus", [
    "ACTIVE",
    "INACTIVE",
  ]);
  const entity = chrome.t("major");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "code",
        label: labels.code,
        type: "text",
        required: !major,
        placeholder: "CS",
      },
      { name: "name", label: labels.name, type: "text", required: !major },
      {
        name: "description",
        label: labels.description,
        type: "textarea",
        full: true,
        nullable: true,
      },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [major, labels, statuses],
  );

  return (
    <EntityFormDialog
      mode={major ? "edit" : "create"}
      title={major ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        major ? chrome.t("admin.majorSaved") : chrome.t("admin.majorAdded")
      }
      fields={major ? fields.filter((f) => f.name !== "code") : fields}
      initial={
        major
          ? {
              code: major.code,
              name: major.name,
              description: major.description ?? "",
              status: major.status,
            }
          : { status: "ACTIVE" }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return major ? updateMajor(major.id, payload) : createMajor(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Program ──

export function ProgramDialog({
  program,
  majors,
  onSaved,
}: {
  program?: Program;
  majors: Major[];
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const statuses = useStatusOptions("academics.entityStatus", [
    "ACTIVE",
    "INACTIVE",
  ]);
  const entity = chrome.t("program");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "major_id",
        label: labels.major,
        type: "select",
        required: true,
        full: true,
        options: majors.map((major) => ({ value: major.id, label: major.name })),
      },
      {
        name: "code",
        label: labels.code,
        type: "text",
        required: !program,
        placeholder: "BSCS",
      },
      { name: "name", label: labels.name, type: "text", required: !program },
      {
        name: "duration_years",
        label: chrome.t("duration"),
        type: "number",
        min: 1,
        max: 10,
      },
      {
        name: "description",
        label: labels.description,
        type: "textarea",
        full: true,
        nullable: true,
      },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [program, labels, statuses, majors, chrome],
  );

  return (
    <EntityFormDialog
      mode={program ? "edit" : "create"}
      title={program ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        program ? chrome.t("admin.programSaved") : chrome.t("admin.programAdded")
      }
      fields={program ? fields.filter((f) => f.name !== "code") : fields}
      initial={
        program
          ? {
              major_id: program.major_id,
              code: program.code,
              name: program.name,
              duration_years: program.duration_years
                ? String(program.duration_years)
                : "",
              description: program.description ?? "",
              status: program.status,
            }
          : {
              major_id: majors[0]?.id ?? "",
              status: "ACTIVE",
              duration_years: "",
            }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return program
          ? updateProgram(program.id, payload)
          : createProgram(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Program offering ──

export function ProgramOfferingDialog({
  offering,
  periods,
  programs,
  onSaved,
}: {
  offering?: ProgramOffering;
  periods: AcademicPeriod[];
  programs: Program[];
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const tCommon = useTranslations("common");
  const entity = chrome.t("programOffering");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "academic_period_id",
        label: labels.period,
        type: "select",
        required: !offering,
        full: true,
        options: periods.map((period) => ({ value: period.id, label: period.name })),
      },
      {
        name: "source_id",
        label: labels.sourceId,
        type: "text",
        required: !offering,
        placeholder: "SCU-2026A-AI",
      },
      { name: "name", label: labels.name, type: "text", required: !offering },
      { name: "name_zh", label: labels.nameZh, type: "text", nullable: true },
      {
        name: "program_id",
        label: labels.program,
        type: "select",
        full: true,
        nullable: true,
        options: [
          { value: "", label: tCommon("states.notSet") },
          ...programs.map((program) => ({ value: program.id, label: program.name })),
        ],
      },
    ],
    [offering, labels, periods, programs, tCommon],
  );

  const editableFields = offering
    ? fields.filter(
        (field) => field.name !== "academic_period_id" && field.name !== "source_id",
      )
    : fields;

  return (
    <EntityFormDialog
      mode={offering ? "edit" : "create"}
      title={offering ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        offering
          ? chrome.t("admin.programOfferingSaved")
          : chrome.t("admin.programOfferingAdded")
      }
      fields={editableFields}
      initial={
        offering
          ? {
              academic_period_id: offering.academic_period_id,
              source_id: offering.source_id,
              name: offering.name,
              name_zh: offering.name_zh ?? "",
              program_id: offering.program_id ?? "",
            }
          : {
              academic_period_id: periods[0]?.id ?? "",
              source_id: "",
              name: "",
              name_zh: "",
              program_id: "",
            }
      }
      onSubmit={(values) => {
        const payload = toPayload(editableFields, values);
        return offering
          ? updateProgramOffering(offering.id, payload)
          : createProgramOffering(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Course ──

export function CourseDialog({
  course,
  programs,
  onSaved,
}: {
  course?: Course;
  programs: Program[];
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const tCommon = useTranslations("common");
  const statuses = useStatusOptions("academics.entityStatus", [
    "ACTIVE",
    "INACTIVE",
  ]);
  const entity = chrome.t("course");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "code",
        label: labels.code,
        type: "text",
        placeholder: "CS101",
      },
      { name: "name", label: labels.name, type: "text", required: !course },
      {
        name: "program_id",
        label: labels.program,
        type: "select",
        full: true,
        // A course may sit outside any programme (a service course), which the
        // first option represents.
        options: [
          { value: "", label: tCommon("states.notSet") },
          ...programs.map((program) => ({
            value: program.id,
            label: program.name,
          })),
        ],
      },
      {
        name: "credits",
        label: chrome.t("credits"),
        type: "number",
        min: 0,
        max: 20,
        nullable: true,
      },
      {
        name: "semester",
        label: labels.semester,
        type: "number",
        min: 1,
        max: 12,
        nullable: true,
      },
      {
        name: "description",
        label: labels.description,
        type: "textarea",
        full: true,
        nullable: true,
      },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [course, labels, statuses, programs, chrome, tCommon],
  );

  return (
    <EntityFormDialog
      mode={course ? "edit" : "create"}
      title={course ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        course ? chrome.t("admin.courseSaved") : chrome.t("admin.courseAdded")
      }
      fields={course ? fields.filter((f) => f.name !== "code") : fields}
      initial={
        course
          ? {
              code: course.code ?? "",
              name: course.name,
              program_id: course.program_id ?? "",
              credits: course.credits === null || course.credits === undefined ? "" : String(course.credits),
              semester: course.semester ? String(course.semester) : "",
              description: course.description ?? "",
              status: course.status,
            }
          : {
              status: "ACTIVE",
              program_id: programs[0]?.id ?? "",
            }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return course ? updateCourse(course.id, payload) : createCourse(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Academic period ──

export function PeriodDialog({
  period,
  onSaved,
}: {
  period?: AcademicPeriod;
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const statuses = useStatusOptions("academics.periodStatus", [
    "PLANNED",
    "ACTIVE",
    "COMPLETED",
    "CANCELLED",
  ]);
  const entity = chrome.t("academicPeriod");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "code",
        label: labels.code,
        type: "text",
        required: !period,
        placeholder: "2026F",
      },
      { name: "name", label: labels.name, type: "text", required: !period },
      {
        name: "start_date",
        label: labels.startDate,
        type: "date",
        required: true,
      },
      { name: "end_date", label: labels.endDate, type: "date", required: true },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [period, labels, statuses],
  );

  return (
    <EntityFormDialog
      mode={period ? "edit" : "create"}
      title={period ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        period ? chrome.t("admin.periodSaved") : chrome.t("admin.periodAdded")
      }
      fields={
        period
          ? fields.filter(
              (f) =>
                f.name !== "code" &&
                !(
                  (period.has_dependants ||
                    period.status === "COMPLETED") &&
                  (f.name === "start_date" || f.name === "end_date")
                ),
            )
          : fields
      }
      initial={
        period
          ? {
              code: period.code,
              name: period.name,
              start_date: period.start_date,
              end_date: period.end_date,
              status: period.status,
            }
          : { status: "PLANNED" }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return period ? updatePeriod(period.id, payload) : createPeriod(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Classroom ──

export function ClassroomDialog({
  classroom,
  onSaved,
}: {
  classroom?: Classroom;
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const statuses = useStatusOptions("academics.classroomStatus", [
    "AVAILABLE",
    "UNAVAILABLE",
    "MAINTENANCE",
  ]);
  const entity = chrome.t("classroom");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "room_code",
        label: labels.roomCode,
        type: "text",
        required: !classroom,
        placeholder: "A-204",
      },
      { name: "name", label: labels.name, type: "text", nullable: true },
      { name: "building", label: labels.building, type: "text", nullable: true },
      {
        name: "capacity",
        label: labels.capacity,
        type: "number",
        min: 1,
        max: 1000,
        nullable: true,
      },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [classroom, labels, statuses],
  );

  return (
    <EntityFormDialog
      mode={classroom ? "edit" : "create"}
      title={classroom ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        classroom
          ? chrome.t("admin.classroomSaved")
          : chrome.t("admin.classroomAdded")
      }
      fields={classroom ? fields.filter((f) => f.name !== "room_code") : fields}
      initial={
        classroom
          ? {
              room_code: classroom.room_code,
              name: classroom.name ?? "",
              building: classroom.building ?? "",
              capacity:
                classroom.capacity === null || classroom.capacity === undefined
                  ? ""
                  : String(classroom.capacity),
              status: classroom.status,
            }
          : { status: "AVAILABLE" }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return classroom
          ? updateClassroom(classroom.id, payload)
          : createClassroom(payload);
      }}
      onSaved={onSaved}
    />
  );
}

// ── Shared section offerings ──

export function SectionOfferingsDialog({
  section,
  offerings,
  onSaved,
}: {
  section: ClassSection;
  offerings: ProgramOffering[];
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("academics");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);
  const [selection, setSelection] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  function openWith() {
    setSelection(section.program_offerings.map((offering) => offering.id));
    setFailure(null);
    setOpen(true);
  }

  function toggle(offeringId: string) {
    setSelection((current) =>
      current.includes(offeringId)
        ? current.filter((id) => id !== offeringId)
        : [...current, offeringId],
    );
  }

  async function save() {
    setBusy(true);
    setFailure(null);
    try {
      await setClassSectionProgramOfferings(section.id, selection);
      toast.success(t("sectionOfferingsSaved"));
      await onSaved();
      setOpen(false);
    } catch (err) {
      setFailure(normalizeApiError(err, "section offerings"));
    } finally {
      setBusy(false);
    }
  }

  const localized = localizeError(failure);

  return (
    <>
      <Button variant="outline" size="sm" onClick={openWith}>
        <Settings2 className="me-1 h-4 w-4" aria-hidden="true" />
        {t("manageSectionOfferings")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("sectionOfferings")}</DialogTitle>
            <DialogDescription>{t("sectionOfferingsHint")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            {offerings.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("noProgramOfferings")}
              </p>
            ) : (
              offerings.map((offering) => (
                <label
                  key={offering.id}
                  className="flex cursor-pointer items-start gap-3 rounded-md border border-border/70 p-3 text-sm"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4"
                    checked={selection.includes(offering.id)}
                    onChange={() => toggle(offering.id)}
                  />
                  <span className="min-w-0">
                    <span className="block font-medium">{offering.name}</span>
                    <span className="block font-mono text-xs text-muted-foreground">
                      {offering.source_id}
                    </span>
                  </span>
                </label>
              ))
            )}
          </div>

          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localized.message}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button onClick={() => void save()} disabled={busy || offerings.length === 0}>
              {busy ? tCommon("states.saving") : tCommon("actions.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ── Class section ──

export function ClassSectionDialog({
  section,
  courses,
  periods,
  onSaved,
}: {
  section?: ClassSection;
  courses: Course[];
  periods: AcademicPeriod[];
  onSaved: () => Promise<void> | void;
}) {
  const labels = useFieldLabels();
  const chrome = useDialogChrome();
  const statuses = useStatusOptions("academics.periodStatus", [
    "PLANNED",
    "ACTIVE",
    "COMPLETED",
    "CANCELLED",
  ]);
  const entity = chrome.t("classSection");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "course_id",
        label: labels.course,
        type: "select",
        required: true,
        full: true,
        options: courses.map((course) => ({
          value: course.id,
          label: [course.code, course.name].filter(Boolean).join(" — ") || course.name,
        })),
      },
      {
        name: "academic_period_id",
        label: labels.period,
        type: "select",
        required: true,
        full: true,
        options: periods.map((period) => ({
          value: period.id,
          label: period.name,
        })),
      },
      {
        name: "section_code",
        label: chrome.t("sectionCode"),
        type: "text",
        placeholder: "A",
        nullable: true,
      },
      {
        name: "capacity",
        label: labels.capacity,
        type: "number",
        min: 1,
        max: 500,
        nullable: true,
      },
      {
        name: "status",
        label: labels.status,
        type: "select",
        options: statuses,
      },
    ],
    [labels, statuses, courses, periods, chrome],
  );

  return (
    <EntityFormDialog
      mode={section ? "edit" : "create"}
      title={section ? chrome.editTitle(entity) : chrome.createTitle(entity)}
      description={chrome.description}
      triggerLabel={chrome.triggerLabel(entity)}
      submitLabel={chrome.submitLabel}
      savingLabel={chrome.savingLabel}
      cancelLabel={chrome.cancelLabel}
      successMessage={
        section ? chrome.t("admin.classSaved") : chrome.t("admin.classAdded")
      }
      fields={fields}
      initial={
        section
          ? {
              course_id: section.course_id,
              academic_period_id: section.academic_period_id,
              section_code: section.section_code ?? "",
              capacity:
                section.capacity === null || section.capacity === undefined
                  ? ""
                  : String(section.capacity),
              status: section.status,
            }
          : {
              course_id: courses[0]?.id ?? "",
              academic_period_id: periods[0]?.id ?? "",
              status: "PLANNED",
            }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        return section
          ? updateClassSection(section.id, payload)
          : createClassSection(payload);
      }}
      onSaved={onSaved}
    />
  );
}
