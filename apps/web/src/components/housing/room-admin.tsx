"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, UserPlus } from "lucide-react";
import {
  createAssignment,
  createBed,
  endAssignment,
  getRoom,
  transferStudent,
  updateBed,
  updateRoom,
  type RoomStatus,
} from "@/lib/housing-api";
import { studentApi } from "@/lib/student-api";
import { useAuth } from "@/lib/auth-context";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FilterSelect } from "@/components/ui/filter-select";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import type { BedBrief, HousingOverviewBuilding, RoomDetail } from "@/types/housing";
import type { StudentBrief } from "@/types/student";

/**
 * Room administration.
 *
 * Until Stage 8B the housing module could be browsed but not operated: the API
 * client had `createAssignment` and `transferStudent`, and nothing in the UI
 * called them, so placing a student required curl. These dialogs are the
 * operational surface.
 *
 * Every rule stays in the backend. The UI offers valid choices and shows the
 * reason a refused action was refused, but the protection is the API's — a
 * hidden button is never the boundary.
 */

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Rooms with at least one free bed, for the transfer destination picker.
 *
 * Built from the overview, which is a single request for the whole estate. The
 * specific bed is chosen once a room is picked, because free bed ids are not in
 * the overview — and a destination has to name a bed, not just a room.
 */
function roomsWithSpace(buildings: HousingOverviewBuilding[]) {
  return buildings.flatMap((building) =>
    building.floors.flatMap((floor) =>
      floor.rooms
        .filter((room) => room.status === "AVAILABLE" && room.available > 0)
        .map((room) => ({
          buildingName: building.name,
          floorNumber: floor.floor_number,
          roomId: room.id,
          roomNumber: room.room_number,
          available: room.available,
        })),
    ),
  );
}

interface AssignDialogProps {
  bed: BedBrief;
  onDone: () => Promise<void> | void;
}

export function AssignBedDialog({ bed, onDone }: AssignDialogProps) {
  const t = useTranslations("housing.admin");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [students, setStudents] = useState<StudentBrief[]>([]);
  const [studentId, setStudentId] = useState("");
  const [startDate, setStartDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [validation, setValidation] = useState("");

  async function runSearch(term: string) {
    setSearch(term);
    setStudentId("");
    try {
      const result = await studentApi.listStudents({ search: term, page_size: 10 });
      setStudents(result.items);
    } catch {
      setStudents([]);
    }
  }

  async function submit() {
    const student = students.find((candidate) => candidate.id === studentId);
    if (!student) {
      setValidation(t("selectStudentFirst"));
      return;
    }

    setBusy(true);
    setFailure(null);
    setValidation("");
    try {
      await createAssignment({
        // An assignment is keyed on the account, not the student record.
        student_id: student.user_id,
        bed_id: bed.id,
        start_date: `${startDate}T00:00:00Z`,
      });
      toast.success(t("assigned"));
      await onDone();
      setOpen(false);
      setSearch("");
      setStudents([]);
      setStudentId("");
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <UserPlus className="me-1 h-4 w-4" aria-hidden="true" />
        {t("assignStudent")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("assignTitle")}</DialogTitle>
            <DialogDescription>
              {t("assignDescription", { bed: bed.label ?? bed.display_number })}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label htmlFor="student-search" className="text-sm font-medium">
                {t("findStudent")}
              </label>
              <Input
                id="student-search"
                value={search}
                onChange={(event) => void runSearch(event.target.value)}
                placeholder={t("findStudentPlaceholder")}
              />
              {students.length > 0 && (
                <div
                  role="radiogroup"
                  aria-label={t("findStudent")}
                  className="max-h-56 space-y-1 overflow-y-auto rounded-md border p-2"
                >
                  {students.map((student) => (
                    <label
                      key={student.id}
                      className="flex cursor-pointer items-center gap-3 rounded-md p-2 text-sm hover:bg-muted"
                    >
                      <input
                        type="radio"
                        name="assign-student"
                        value={student.id}
                        checked={studentId === student.id}
                        onChange={() => setStudentId(student.id)}
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {student.last_name}, {student.first_name}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {student.student_id}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <label htmlFor="assign-start" className="text-sm font-medium">
                {t("startDate")}
              </label>
              <Input
                id="assign-start"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>

            {(failure || validation) && (
              <p role="alert" className="text-sm text-destructive">
                {validation || localizeError(failure).message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button onClick={() => void submit()} disabled={busy}>
              {busy ? tCommon("states.saving") : tCommon("actions.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface MoveDialogProps {
  bed: BedBrief;
  buildings: HousingOverviewBuilding[];
  onDone: () => Promise<void> | void;
}

export function MoveStudentDialog({ bed, buildings, onDone }: MoveDialogProps) {
  const t = useTranslations("housing.admin");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [open, setOpen] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [bedId, setBedId] = useState("");
  const [freeBeds, setFreeBeds] = useState<BedBrief[]>([]);
  const [transferDate, setTransferDate] = useState(today());
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [validation, setValidation] = useState("");

  const options = useMemo(() => roomsWithSpace(buildings), [buildings]);

  async function chooseRoom(id: string) {
    setRoomId(id);
    setBedId("");
    setFreeBeds([]);
    if (!id) return;
    try {
      const room = await getRoom(id);
      setFreeBeds(room.beds.filter((candidate) => !candidate.is_occupied));
    } catch {
      setValidation(t("destinationUnavailable"));
    }
  }

  async function submit() {
    if (!bed.assignment_id || !bedId) {
      setValidation(t("selectDestinationFirst"));
      return;
    }

    setBusy(true);
    setFailure(null);
    setValidation("");
    try {
      await transferStudent(bed.assignment_id, {
        new_bed_id: bedId,
        transfer_date: `${transferDate}T00:00:00Z`,
      });
      toast.success(t("transferred"));
      await onDone();
      setOpen(false);
      setRoomId("");
      setBedId("");
      setFreeBeds([]);
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        {t("moveStudent")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("moveTitle")}</DialogTitle>
            <DialogDescription>
              {t("moveDescription", {
                student: bed.student_name ?? tCommon("states.unknown"),
              })}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
          {options.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noFreeBeds")}</p>
          ) : (
            <div className="space-y-2">
              <FilterSelect
                label={t("destination")}
                showLabel
                value={roomId}
                onChange={(value) => void chooseRoom(value)}
                options={[
                  { value: "", label: t("chooseDestination") },
                  ...options.map((option) => ({
                    value: option.roomId,
                    label: t("destinationOption", {
                      building: option.buildingName,
                      floor: option.floorNumber,
                      room: option.roomNumber,
                      available: option.available,
                    }),
                  })),
                ]}
              />
              {roomId && (
                <FilterSelect
                  label={t("destinationBed")}
                  showLabel
                  value={bedId}
                  onChange={setBedId}
                  options={[
                    { value: "", label: t("chooseBed") },
                    ...freeBeds.map((candidate) => ({
                      value: candidate.id,
                      label: t("bedNumber", { number: candidate.display_number }),
                    })),
                  ]}
                />
              )}
              <p className="text-xs text-muted-foreground">{t("destinationHint")}</p>
            </div>
          )}

          <div className="space-y-2">
            <label htmlFor="move-date" className="text-sm font-medium">
              {t("transferDate")}
            </label>
            <Input
              id="move-date"
              type="date"
              value={transferDate}
              onChange={(event) => setTransferDate(event.target.value)}
            />
          </div>

          {(failure || validation) && (
            <p role="alert" className="text-sm text-destructive">
              {validation || localizeError(failure).message}
            </p>
          )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button
              onClick={() => void submit()}
              disabled={busy || options.length === 0 || !bedId}
            >
              {busy ? tCommon("states.saving") : tCommon("actions.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function EndAssignmentButton({
  bed,
  onDone,
}: {
  bed: BedBrief;
  onDone: () => Promise<void> | void;
}) {
  const t = useTranslations("housing.admin");
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    if (!bed.assignment_id) return;
    setBusy(true);
    setFailure(null);
    try {
      await endAssignment(bed.assignment_id);
      toast.success(t("ended"));
      await onDone();
      setOpen(false);
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        {t("endAssignment")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("endTitle")}</DialogTitle>
            <DialogDescription>
              {t("endDescription", {
                student: bed.student_name ?? "",
              })}
            </DialogDescription>
          </DialogHeader>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localizeError(failure).message}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("keepAssignment")}
            </Button>
            <Button variant="destructive" onClick={() => void submit()} disabled={busy}>
              {t("endAssignment")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/**
 * Structural controls for one room: operational status, adding a bed, retiring
 * an empty bed, and renaming one.
 */
export function RoomStructureControls({
  room,
  onChanged,
}: {
  room: RoomDetail;
  onChanged: (room: RoomDetail) => void;
}) {
  const t = useTranslations("housing.admin");
  const localizeError = useErrorMessage();
  const { hasPermission } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [validation, setValidation] = useState("");

  const mayCreate = hasPermission("housing.create");
  const mayEdit = hasPermission("housing.edit");

  async function apply(action: () => Promise<RoomDetail>, successMessage: string) {
    setBusy(true);
    setFailure(null);
    setValidation("");
    try {
      onChanged(await action());
      toast.success(successMessage);
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-end gap-3">
        {mayEdit && (
          <FilterSelect
            label={t("roomStatus")}
            showLabel
            className="w-full sm:w-64"
            value={room.status}
            onChange={(value) =>
              void apply(
                () => updateRoom(room.id, { status: value as RoomStatus }),
                t("statusChanged"),
              )
            }
            options={[
              { value: "AVAILABLE", label: t("statusAvailable") },
              { value: "RESERVED", label: t("statusReserved") },
              { value: "OUT_OF_SERVICE", label: t("statusOutOfService") },
            ]}
          />
        )}

        {mayCreate && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void apply(() => createBed(room.id), t("bedAdded"))}
          >
            <Plus className="me-1 h-4 w-4" aria-hidden="true" />
            {t("addBed")}
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{t("capacityRule")}</p>

      {(failure || validation) && (
        <p role="alert" className="text-sm text-destructive">
          {validation || localizeError(failure).message}
        </p>
      )}

      {mayEdit && room.beds.length > 0 && (
        <ul className="space-y-2">
          {room.beds.map((bed) => (
            <li key={bed.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-24 font-medium">
                {t("bedNumber", { number: bed.display_number })}
                {bed.label ? ` · ${bed.label}` : ""}
              </span>
              {bed.is_occupied ? (
                <span className="text-muted-foreground">{t("occupiedBedLocked")}</span>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    void apply(() => updateBed(bed.id, { is_active: false }), t("bedRetired"))
                  }
                >
                  {t("retireBed")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Whether a user may do anything on this page at all. */
export function useHousingAdmin() {
  const { hasPermission } = useAuth();
  return {
    canAssign: hasPermission("housing.assign"),
    canTransfer: hasPermission("housing.transfer"),
    canCreate: hasPermission("housing.create"),
    canEdit: hasPermission("housing.edit"),
  };
}
