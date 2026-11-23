"use client";

import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { occupancyDot, occupancyPercent } from "@/lib/occupancy";
import { useStatusLabel } from "@/lib/use-status-label";
import type { HousingOverviewBuilding } from "@/types/housing";

const MAX_FLOORS = 4;

/**
 * Compact room-level occupancy map for an overview building card.
 *
 * Every square maps to a real room returned by `/housing/overview`; the rows
 * are floors and the colour mirrors the licensed occupancy legend. It is
 * deliberately non-interactive because the whole card already opens the
 * building — the map adds a readable shape of the building, not a second set of
 * competing hit targets.
 */
export function BuildingRoomMap({
  floors,
  buildingName,
}: {
  floors: HousingOverviewBuilding["floors"];
  buildingName: string;
}) {
  const t = useTranslations("housing");
  const statusLabel = useStatusLabel();

  if (floors.length === 0) return null;

  const visible = floors.slice(0, MAX_FLOORS);
  const hiddenFloors = Math.max(0, floors.length - visible.length);
  const totalRooms = floors.reduce((sum, floor) => sum + floor.room_count, 0);
  const occupied = floors.reduce((sum, floor) => sum + floor.occupied_count, 0);

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
        <span className="font-semibold uppercase tracking-[0.12em]">{t("roomGrid")}</span>
        <span className="tabular-nums">{occupancyPercent(occupied, totalRooms)}%</span>
      </div>
      <div
        className="motion-room-grid space-y-1 rounded-lg border border-border/70 bg-muted/20 p-2"
        role="img"
        aria-label={`${buildingName}: ${t("roomGrid")}. ${t("occupied")} ${occupied}/${totalRooms}`}
      >
        {visible.map((floor) => (
          <div key={floor.id} className="flex items-center gap-1.5">
            <span className="w-3 shrink-0 text-end text-[9px] font-medium tabular-nums text-muted-foreground">
              {floor.floor_number}
            </span>
            <div className="flex min-w-0 flex-1 gap-0.5">
              {floor.rooms.slice(0, 24).map((room) => (
                <span
                  key={room.id}
                  title={`${room.room_number}: ${statusLabel(
                    room.occupancy_status,
                    "housing.occupancyStatus",
                  )}`}
                  className={cn(
                    "h-2.5 min-w-1 flex-1 rounded-[2px]",
                    occupancyDot(room.occupancy_status),
                  )}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[9px] text-muted-foreground">
        <span>{t("roomGridHint")}</span>
        {hiddenFloors > 0 && (
          <span className="shrink-0 tabular-nums">
            {t("moreFloors", { count: hiddenFloors })}
          </span>
        )}
      </div>
    </div>
  );
}
