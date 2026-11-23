"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link } from "@/i18n/navigation";
import { getBuilding, getFloorRooms } from "@/lib/housing-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { roomSurface } from "@/lib/occupancy";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { Button } from "@/components/ui/button";
import { OccupancyLegend } from "@/components/housing/occupancy-legend";
import { AddRoomDialog } from "@/components/housing/structure-dialogs";
import { useAuth } from "@/lib/auth-context";
import { useRouter } from "@/i18n/navigation";
import type { BuildingDetail, RoomBrief } from "@/types/housing";

interface FloorBundle {
  building: BuildingDetail;
  rooms: RoomBrief[];
}

export default function FloorPage() {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const params = useParams<{ buildingId: string; floorId: string }>();
  const buildingId = params?.buildingId ?? "";
  const floorId = params?.floorId ?? "";
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const { hasPermission } = useAuth();
  const router = useRouter();

  const fetchFloor = useCallback(async (): Promise<FloorBundle> => {
    const [building, rooms] = await Promise.all([
      getBuilding(buildingId),
      getFloorRooms(floorId),
    ]);
    return { building, rooms };
  }, [buildingId, floorId]);

  const { data, loading, error, refetch } = useApi<FloorBundle>(
    fetchFloor,
    [buildingId, floorId],
    "floor detail",
  );

  const localized = localizeError(error);

  if (loading) {
    return (
      <AppShell>
        <LoadingState />
      </AppShell>
    );
  }

  if (error || !data) {
    return (
      <AppShell>
        <ErrorState message={localized.message} hint={localized.hint} onRetry={refetch} />
        <div className="mt-4 flex justify-center">
          <Button asChild variant="outline" size="sm">
            <Link href="/app/housing">{t("title")}</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  const { building, rooms } = data;
  const floor = building.floors.find((candidate) => candidate.id === floorId);

  if (!floor) {
    return (
      <AppShell>
        <ErrorState title={tErrors("notFound")} message={t("noRooms")} />
        <div className="mt-4 flex justify-center">
          <Button asChild variant="outline" size="sm">
            <Link href={`/app/housing/${buildingId}`}>
              {building.name}
            </Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  const occupied = rooms.reduce((sum, room) => sum + room.occupied, 0);
  const capacity = rooms.reduce((sum, room) => sum + room.capacity, 0);

  return (
    <AppShell>
      <PageHeader
        title={t("floorNumber", { number: floor.floor_number })}
        description={`${building.name} · ${tCommon(
          "counts.rooms",
          { count: rooms.length },
        )} · ${t("occupancySummary", { occupied, capacity })}`}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title"), href: "/app/housing" },
          {
            label: building.name,
            href: `/app/housing/${buildingId}`,
          },
          { label: t("floorNumber", { number: floor.floor_number }) },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge tone={toneForStatus(floor.occupancy_status)}>
              {statusLabel(floor.occupancy_status, "housing.occupancyStatus")}
            </StatusBadge>
            {hasPermission("housing.create") && (
              <AddRoomDialog
                floorId={floorId}
                onCreated={(roomId) => {
                  // Straight into the room that was just created, so the beds
                  // can be assigned without hunting for the tile.
                  void refetch();
                  router.push(`/app/housing/${buildingId}/${floorId}/${roomId}`);
                }}
              />
            )}
          </div>
        }
      />

      <StatGrid className="lg:grid-cols-4">
        <StatCard label={t("rooms")} value={rooms.length} />
        <StatCard label={t("beds")} value={capacity} />
        <StatCard label={t("occupied")} value={occupied} tone="info" />
        <StatCard label={t("available")} value={capacity - occupied} tone="success" />
      </StatGrid>

      <OccupancyLegend className="mb-4" />

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {t("roomGrid")}
      </h2>

      {rooms.length === 0 ? (
        <EmptyState title={t("noRooms")} />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {rooms.map((room) => {
            const statusText = statusLabel(room.occupancy_status, "housing.occupancyStatus");
            return (
              <Link
                key={room.id}
                href={`/app/housing/${buildingId}/${floorId}/${room.id}`}
                aria-label={t("roomOccupancyLabel", {
                  room: room.room_number,
                  occupied: room.occupied,
                  capacity: room.capacity,
                  status: statusText,
                })}
                className={`rounded-lg border p-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${roomSurface(
                  room.occupancy_status,
                )}`}
              >
                <div className="flex flex-col items-center gap-2 text-center">
                  <p className="text-lg font-semibold tabular-nums">{room.room_number}</p>
                  <p className="text-sm font-medium tabular-nums">
                    {room.occupied}/{room.capacity}
                  </p>
                  <StatusBadge tone={toneForStatus(room.occupancy_status)}>
                    {statusText}
                  </StatusBadge>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
