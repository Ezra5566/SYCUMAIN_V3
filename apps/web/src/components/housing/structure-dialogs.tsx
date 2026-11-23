"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { createBuilding, createFloor, createRoom } from "@/lib/housing-api";
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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";

/**
 * Structure creation dialogs.
 *
 * The estate was seed-only before Stage 8B, so these three dialogs are what
 * turn "the dormitory matches the seed script" into "management can add the
 * next building". They only create; renaming and archiving happen inline where
 * the record is displayed.
 */

export function AddBuildingDialog({ onCreated }: { onCreated: () => Promise<void> | void }) {
  const t = useTranslations("housing.admin");
  const localizeError = useErrorMessage();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await createBuilding({ name, description: description || undefined });
      toast.success(t("buildingAdded"));
      await onCreated();
      setOpen(false);
      setName("");
      setDescription("");
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus className="me-1 h-4 w-4" aria-hidden="true" />
        {t("addBuilding")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("addBuildingTitle")}</DialogTitle>
            <DialogDescription>{t("addBuildingDescription")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label htmlFor="building-name" className="text-sm font-medium">
                {t("buildingName")}
              </label>
              <Input
                id="building-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("buildingNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="building-description" className="text-sm font-medium">
                {t("buildingDescription")}
              </label>
              <Textarea
                id="building-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
              />
            </div>
            {failure && (
              <p role="alert" className="text-sm text-destructive">
                {localizeError(failure).message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={() => void submit()} disabled={busy || name.trim().length === 0}>
              {busy ? t("saving") : t("addBuilding")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface AddFloorProps {
  buildingId: string;
  /** Suggested number: one above the highest floor already in the building. */
  nextFloorNumber: number;
  onCreated: () => Promise<void> | void;
}

export function AddFloorDialog({ buildingId, nextFloorNumber, onCreated }: AddFloorProps) {
  const t = useTranslations("housing.admin");
  const localizeError = useErrorMessage();
  const [floorNumber, setFloorNumber] = useState(String(nextFloorNumber));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await createFloor(buildingId, Number(floorNumber));
      toast.success(t("floorAdded"));
      await onCreated();
      setOpen(false);
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="me-1 h-4 w-4" aria-hidden="true" />
        {t("addFloor")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("addFloorTitle")}</DialogTitle>
            <DialogDescription>{t("addFloorDescription")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2 py-2">
            <label htmlFor="floor-number" className="text-sm font-medium">
              {t("floorNumber")}
            </label>
            <Input
              id="floor-number"
              type="number"
              value={floorNumber}
              onChange={(event) => setFloorNumber(event.target.value)}
            />
          </div>

          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localizeError(failure).message}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={() => void submit()} disabled={busy || floorNumber === ""}>
              {busy ? t("saving") : t("addFloor")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface AddRoomProps {
  floorId: string;
  onCreated: (roomId: string) => Promise<void> | void;
}

export function AddRoomDialog({ floorId, onCreated }: AddRoomProps) {
  const t = useTranslations("housing.admin");
  const localizeError = useErrorMessage();
  const [roomNumber, setRoomNumber] = useState("");
  // No assumed default beyond the seed convention: capacity is an explicit
  // choice, and the beds are created with it.
  const [capacity, setCapacity] = useState("4");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      const room = await createRoom(floorId, {
        room_number: roomNumber,
        capacity: Number(capacity),
      });
      toast.success(t("roomAdded"));
      await onCreated(room.id);
      setOpen(false);
      setRoomNumber("");
    } catch (error) {
      setFailure(normalizeApiError(error, "housing"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="me-1 h-4 w-4" aria-hidden="true" />
        {t("addRoom")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("addRoomTitle")}</DialogTitle>
            <DialogDescription>{t("addRoomDescription")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label htmlFor="room-number" className="text-sm font-medium">
                {t("roomNumber")}
              </label>
              <Input
                id="room-number"
                value={roomNumber}
                onChange={(event) => setRoomNumber(event.target.value)}
                placeholder={t("roomNumberPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="room-capacity" className="text-sm font-medium">
                {t("capacity")}
              </label>
              <Input
                id="room-capacity"
                type="number"
                min={0}
                max={20}
                value={capacity}
                onChange={(event) => setCapacity(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t("capacityRule")}</p>
            </div>
            {failure && (
              <p role="alert" className="text-sm text-destructive">
                {localizeError(failure).message}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              onClick={() => void submit()}
              disabled={busy || roomNumber.trim().length === 0 || capacity === ""}
            >
              {busy ? t("saving") : t("addRoom")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
