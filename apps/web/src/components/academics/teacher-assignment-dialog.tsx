"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Trash2, Users } from "lucide-react";
import {
  assignTeacher,
  listClassTeachers,
  listTeachableStaff,
  removeTeacher,
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
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import type { ClassSection, TeachableStaff, TeacherAssignment } from "@/types/academic";

/**
 * Class-section teacher assignment.
 *
 * The list of eligible staff comes from the API rather than a free-text UUID.
 * Removing an assignment deactivates it server-side, keeping the historical
 * teaching record instead of deleting it.
 */
export function TeacherAssignmentsDialog({
  section,
  onSaved,
}: {
  section: ClassSection;
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("institutional");
  const tAcademics = useTranslations("academics");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);
  const [staff, setStaff] = useState<TeachableStaff[]>([]);
  const [assignments, setAssignments] = useState<TeacherAssignment[]>([]);
  const [staffId, setStaffId] = useState("");
  const [role, setRole] = useState<"PRIMARY" | "ASSISTANT">("PRIMARY");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    try {
      const [people, current] = await Promise.all([
        listTeachableStaff(),
        listClassTeachers(section.id),
      ]);
      const eligible = people.items.filter((person) =>
        person.roles.includes("TEACHER"),
      );
      setStaff(eligible);
      setAssignments(current.filter((assignment) => assignment.is_active));
      setStaffId(eligible[0]?.staff_id ?? "");
    } catch (error) {
      setFailure(normalizeApiError(error, "teacher assignments"));
    } finally {
      setLoading(false);
    }
  }, [section.id]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  async function add() {
    if (!staffId) return;
    setBusy(true);
    setFailure(null);
    try {
      await assignTeacher(section.id, { staff_id: staffId, role });
      toast.success(t("assignmentSaved"));
      await load();
      await onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "assign teacher"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(assignmentId: string) {
    setBusy(true);
    setFailure(null);
    try {
      await removeTeacher(section.id, assignmentId);
      toast.success(t("assignmentRemoved"));
      await load();
      await onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "remove teacher"));
    } finally {
      setBusy(false);
    }
  }

  const assignedIds = new Set(assignments.map((assignment) => assignment.staff_id));
  const available = staff.filter((person) => !assignedIds.has(person.staff_id));

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Users className="me-1 h-4 w-4" aria-hidden="true" />
        {t("teacherAssignments")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("teacherAssignments")}</DialogTitle>
            <DialogDescription>
              {t("teacherAssignmentsDescription")}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold">{t("assignedTeachers")}</h3>
            {loading ? (
              <p className="text-sm text-muted-foreground">
                {tCommon("states.loading")}
              </p>
            ) : assignments.length === 0 ? (
              <EmptyState title={t("noTeacherAssigned")} />
            ) : (
              <ul className="divide-y rounded-md border">
                {assignments.map((assignment) => (
                  <li
                    key={assignment.id}
                    className="flex items-center justify-between gap-3 p-3 text-sm"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">
                        {assignment.staff_name ?? tCommon("states.unknown")}
                      </span>
                      <StatusBadge tone="info">{assignment.role}</StatusBadge>
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={busy}
                      aria-label={`${tCommon("actions.remove")} ${assignment.staff_name ?? ""}`}
                      onClick={() => void remove(assignment.id)}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}

            <div className="space-y-2 rounded-lg border border-border/80 bg-muted/20 p-3">
              <label className="space-y-1.5 text-sm">
                <span className="font-medium">{t("selectTeacher")}</span>
                <select
                  value={staffId}
                  onChange={(event) => setStaffId(event.target.value)}
                  className="h-10 w-full rounded-md border border-input bg-background px-3"
                  disabled={loading || available.length === 0}
                >
                  {available.length === 0 ? (
                    <option value="">{t("noEligibleTeachers")}</option>
                  ) : (
                    available.map((person) => (
                      <option key={person.staff_id} value={person.staff_id}>
                        {person.first_name} {person.last_name}
                        {person.staff_number ? ` · ${person.staff_number}` : ""}
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label className="space-y-1.5 text-sm">
                <span className="font-medium">{tAcademics("teacherRole")}</span>
                <select
                  value={role}
                  onChange={(event) =>
                    setRole(event.target.value as "PRIMARY" | "ASSISTANT")
                  }
                  className="h-10 w-full rounded-md border border-input bg-background px-3"
                >
                  <option value="PRIMARY">{t("primary")}</option>
                  <option value="ASSISTANT">{t("assistant")}</option>
                </select>
              </label>
              <Button
                size="sm"
                onClick={() => void add()}
                disabled={busy || !staffId}
              >
                <Plus className="me-1 h-4 w-4" aria-hidden="true" />
                {t("assignTeacher")}
              </Button>
            </div>

            {failure && (
              <p role="alert" className="text-sm text-destructive">
                {localizeError(failure).message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
