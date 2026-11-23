"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";
import {
  createTimetableEntry,
  deleteTimetableEntry,
  updateTimetableEntry,
} from "@/lib/academic-api";
import {
  EntityFormDialog,
  toPayload,
  type FieldSpec,
} from "@/components/academics/entity-form";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { sectionLabel } from "@/lib/academic-display";
import type {
  Classroom,
  ClassSection,
  TimetableEntry,
} from "@/types/academic";

/**
 * Timetable create/edit/remove.
 *
 * Conflicts are *not* detected here. The API owns the three overlap rules
 * (section, classroom, teacher) plus the classroom-availability rule, and
 * returns a distinct code for each; this component renders the localized
 * sentence that comes back. Re-deriving overlaps in the browser would produce a
 * second, weaker rule set that disagrees with the one that actually writes the
 * row — and it could not see a clash with a session another clerk created a
 * second earlier.
 *
 * The schedule a student or teacher sees is derived from these entries, so
 * editing one propagates everywhere by construction.
 */

/** Weekday order the API uses: 0 = Monday … 6 = Sunday. */
const WEEKDAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

/**
 * An `<input type="time">` submits "HH:MM"; the API's `time` field carries
 * seconds. Appending them here keeps the leniency in the one place that
 * produces the value, rather than loosening the schema for every caller.
 */
function withSeconds(value: string): string {
  return value.length === 5 ? `${value}:00` : value;
}

export function TimetableEntryDialog({
  entry,
  sections,
  classrooms,
  onSaved,
}: {
  entry?: TimetableEntry;
  sections: ClassSection[];
  classrooms: Classroom[];
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("academics");
  const tCommon = useTranslations("common");
  const tDays = useTranslations("academics.days");
  const tFields = useTranslations("academics.fields");
  const tAdmin = useTranslations("academics.admin");

  // Only rooms the school considers usable are offered. The API still refuses a
  // closed room — this just avoids presenting a choice that must be rejected.
  const usableRooms = classrooms.filter((room) => room.status === "AVAILABLE");

  const fields: FieldSpec[] = useMemo(
    () => [
      {
        name: "class_section_id",
        label: t("classSection"),
        type: "select",
        required: true,
        full: true,
        options: sections.map((section) => ({
          value: section.id,
          label: sectionLabel(section),
        })),
      },
      {
        name: "classroom_id",
        label: t("classroom"),
        type: "select",
        full: true,
        nullable: true,
        options: [
          { value: "", label: tCommon("states.notSet") },
          ...usableRooms.map((room) => ({
            value: room.id,
            label: room.building
              ? `${room.room_code} — ${room.building}`
              : room.room_code,
          })),
        ],
      },
      {
        name: "day_of_week",
        label: tFields("day"),
        type: "select",
        required: true,
        options: WEEKDAYS.map((day, index) => ({
          value: String(index),
          label: tDays(day),
        })),
      },
      {
        name: "start_time",
        label: tFields("startTime"),
        type: "time",
        required: true,
      },
      {
        name: "end_time",
        label: tFields("endTime"),
        type: "time",
        required: true,
      },
    ],
    [sections, usableRooms, t, tCommon, tDays, tFields],
  );

  const entity = t("timetable");

  return (
    <EntityFormDialog
      mode={entry ? "edit" : "create"}
      title={`${entry ? tCommon("actions.edit") : tCommon("actions.add")} — ${entity}`}
      description={tAdmin("formDescription")}
      triggerLabel={`${tCommon("actions.add")} ${entity}`}
      submitLabel={tCommon("actions.save")}
      savingLabel={tCommon("states.saving")}
      cancelLabel={tCommon("actions.cancel")}
      successMessage={entry ? tAdmin("timetableSaved") : tAdmin("timetableAdded")}
      fields={fields}
      initial={
        entry
          ? {
              class_section_id: entry.class_section_id,
              classroom_id: entry.classroom_id ?? "",
              day_of_week: String(entry.day_of_week),
              // <input type="time"> expects HH:MM; the API returns HH:MM:SS.
              start_time: entry.start_time.slice(0, 5),
              end_time: entry.end_time.slice(0, 5),
            }
          : {
              class_section_id: sections[0]?.id ?? "",
              day_of_week: "0",
              start_time: "09:00",
              end_time: "10:00",
            }
      }
      onSubmit={(values) => {
        const payload = toPayload(fields, values);
        payload.start_time = withSeconds(String(payload.start_time));
        payload.end_time = withSeconds(String(payload.end_time));
        return entry
          ? updateTimetableEntry(entry.id, payload)
          : createTimetableEntry(payload);
      }}
      onSaved={onSaved}
      variant={entry ? "ghost" : "default"}
      size={entry ? "icon" : "default"}
    />
  );
}

export function RemoveTimetableEntryButton({
  entry,
  onSaved,
}: {
  entry: TimetableEntry;
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("academics.admin");
  const tCommon = useTranslations("common");

  const label = sectionLabel(entry);

  return (
    <ConfirmDialog
      title={t("removeEntryTitle")}
      description={t("removeEntryDescription", { entry: label })}
      confirmLabel={tCommon("actions.remove")}
      triggerLabel={t("removeEntryTitle")}
      triggerIcon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
      variant="destructive"
      size="icon"
      onConfirm={() => deleteTimetableEntry(entry.id)}
      onDone={onSaved}
    />
  );
}
