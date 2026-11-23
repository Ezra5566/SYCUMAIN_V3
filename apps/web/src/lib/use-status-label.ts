"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";

/**
 * Every namespace that holds a status/priority/category label keyed by the raw
 * value the API returns (e.g. `ACTIVE`, `EXPIRING`, `IN_PROGRESS`).
 *
 * Keeping this list in one place means a new module only has to register its
 * namespace here, rather than every page learning how to render its enums.
 */
const STATUS_NAMESPACES = [
  "students.status",
  "immigration.statusLabel",
  "immigration.requestStatus",
  "housing.occupancyStatus",
  "housing.roomStatus",
  "housing.bedStatus",
  "housing.assignmentStatus",
  "academics.periodStatus",
  "academics.entityStatus",
  "academics.classroomStatus",
  "academics.enrollmentStatus",
  "academics.attendanceStatus",
  "academics.assessmentType",
  "announcements.status",
  "announcements.priorities",
  "announcements.audiences",
  "support.status",
  "support.priorities",
  "support.categories",
  "documents.status",
  "documents.types",
] as const;

/** `IN_PROGRESS` -> `In progress` — last-resort readability for an unmapped enum. */
function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * Translate a raw API enum into the user's language.
 *
 * Resolution order:
 *   1. The caller's explicit namespace (`preferredNamespace`), e.g. the housing
 *      page passing `"housing"`.
 *   2. Any registered status namespace that defines the value.
 *   3. A humanized version of the raw value.
 *
 * Step 3 matters: a backend that adds a new enum must degrade to something
 * readable rather than printing a raw token or a missing-key path at a student.
 *
 * A single root translator is used (rather than one per namespace) so the hook
 * count stays constant regardless of how many namespaces are registered.
 */
export function useStatusLabel() {
  const t = useTranslations();

  return useCallback(
    (value: string | null | undefined, preferredNamespace?: string): string => {
      if (!value) return "";

      if (preferredNamespace) {
        const key = `${preferredNamespace}.${value}`;
        if (t.has(key)) return t(key);
      }

      for (const namespace of STATUS_NAMESPACES) {
        const key = `${namespace}.${value}`;
        if (t.has(key)) return t(key);
      }

      return humanize(value);
    },
    [t],
  );
}
