"use client";

import { useCallback } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { UserRound } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { getHousingOverview, getRoom, getRoomHistory } from "@/lib/housing-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { Button } from "@/components/ui/button";
import {
  AssignBedDialog,
  EndAssignmentButton,
  MoveStudentDialog,
  RoomStructureControls,
  useHousingAdmin,
} from "@/components/housing/room-admin";
import type {
  BedBrief,
  HousingAssignmentResponse,
  HousingOverviewBuilding,
  RoomDetail,
} from "@/types/housing";

interface BedCardProps {
  bed: BedBrief;
  buildings: HousingOverviewBuilding[];
  canAssign: boolean;
  canTransfer: boolean;
  onChanged: () => Promise<void> | void;
}

function BedCard({ bed, buildings, canAssign, canTransfer, onChanged }: BedCardProps) {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const statusLabel = useStatusLabel();

  const bedStatus = bed.is_occupied ? "OCCUPIED" : "AVAILABLE";

  return (
    <div
      className={`rounded-lg border p-4 ${
        bed.is_occupied
          ? "border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950"
          : "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">
          {t("bedLabel", { number: bed.display_number })}
          {bed.label ? ` · ${bed.label}` : ""}
        </span>
        <StatusBadge tone={bed.is_occupied ? "info" : "success"}>
          {statusLabel(bedStatus, "housing.bedStatus")}
        </StatusBadge>
      </div>

      {bed.is_occupied ? (
        <div className="flex items-center gap-3">
          <span
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-background"
            aria-hidden="true"
          >
            <UserRound className="h-4 w-4 text-muted-foreground" />
          </span>
          <div className="min-w-0">
            {bed.student_record_id ? (
              <Link
                href={`/app/students/${bed.student_record_id}`}
                className="block truncate rounded-sm text-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {bed.student_name ?? tCommon("states.unknown")}
              </Link>
            ) : (
              <p className="truncate text-sm font-medium">
                {bed.student_name ?? tCommon("states.unknown")}
              </p>
            )}
            {bed.student_record_id && (
              <p className="text-xs text-muted-foreground">{t("assignedTo")}</p>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("noOccupant")}</p>
      )}

      {/* Actions follow permissions; the API enforces them regardless. */}
      {((bed.is_occupied && canTransfer) || (!bed.is_occupied && canAssign)) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {bed.is_occupied ? (
            <>
              <MoveStudentDialog bed={bed} buildings={buildings} onDone={onChanged} />
              <EndAssignmentButton bed={bed} onDone={onChanged} />
            </>
          ) : (
            <AssignBedDialog bed={bed} onDone={onChanged} />
          )}
        </div>
      )}
    </div>
  );
}

export default function RoomPage() {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const params = useParams<{ buildingId: string; floorId: string; roomId: string }>();
  const buildingId = params?.buildingId ?? "";
  const floorId = params?.floorId ?? "";
  const roomId = params?.roomId ?? "";
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const { canAssign, canTransfer, canCreate, canEdit } = useHousingAdmin();

  const fetchRoom = useCallback(() => getRoom(roomId), [roomId]);
  const { data: room, loading, error, refetch } = useApi<RoomDetail>(
    fetchRoom,
    [roomId],
    "room detail",
  );

  // Destinations for a transfer come from the overview: one request for the
  // whole estate rather than a call per building.
  const fetchOverview = useCallback(() => getHousingOverview(), []);
  const { data: overview } = useApi(fetchOverview, [], "housing overview");
  const buildings = overview?.buildings ?? [];

  const fetchHistory = useCallback(() => getRoomHistory(roomId), [roomId]);
  const { data: history } = useApi<HousingAssignmentResponse[]>(
    fetchHistory,
    [roomId],
    "room history",
  );

  const localized = localizeError(error);

  if (loading) {
    return (
      <AppShell>
        <LoadingState />
      </AppShell>
    );
  }

  if (error || !room) {
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

  const buildingLabel = room.building_name ?? t("building");
  const floorLabel =
    room.floor_number != null ? t("floorNumber", { number: room.floor_number }) : t("floor");
  const roomLabel = t("roomNumber", { number: room.room_number });
  const occupancyText = statusLabel(room.occupancy_status, "housing.occupancyStatus");
  const operationalText = statusLabel(room.status, "housing.roomStatus");
  const outOfService = room.status === "OUT_OF_SERVICE";

  return (
    <AppShell>
      <PageHeader
        title={roomLabel}
        description={`${buildingLabel} · ${floorLabel}`}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title"), href: "/app/housing" },
          { label: buildingLabel, href: `/app/housing/${buildingId}` },
          { label: floorLabel, href: `/app/housing/${buildingId}/${floorId}` },
          { label: roomLabel },
        ]}
        actions={
          <StatusBadge tone={toneForStatus(room.occupancy_status)}>
            {occupancyText}
          </StatusBadge>
        }
      />

      {outOfService && (
        <div
          role="status"
          className="mb-4 rounded-lg border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning"
        >
          {t("outOfServiceNotice")}
        </div>
      )}

      <StatGrid className="lg:grid-cols-4">
        <StatCard label={t("capacity")} value={room.capacity} />
        <StatCard label={t("occupied")} value={room.occupied} tone="info" />
        <StatCard label={t("available")} value={room.available} tone="success" />
        <StatCard label={t("operationalStatus")} value={operationalText} />
      </StatGrid>

      {(canCreate || canEdit || canAssign || canTransfer) && (
        <section className="mb-6" aria-labelledby="room-admin-heading">
          <h2
            id="room-admin-heading"
            className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
          >
            {t("admin.heading")}
          </h2>
          <RoomStructureControls room={room} onChanged={() => void refetch()} />
        </section>
      )}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {t("beds")} ({room.beds.length})
      </h2>

      {room.beds.length === 0 ? (
        <Card>
          <CardContent className="pt-6">
            <EmptyState title={t("noBeds")} message={t("assignmentRule")} />
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {room.beds.map((bed) => (
            <BedCard
              key={bed.id}
              bed={bed}
              buildings={buildings}
              canAssign={canAssign}
              canTransfer={canTransfer}
              onChanged={refetch}
            />
          ))}
        </div>
      )}

      <section className="mt-8" aria-labelledby="room-history-heading">
        <h2
          id="room-history-heading"
          className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {t("history")}
        </h2>
        {!history || history.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noHistory")}</p>
        ) : (
          <ul className="space-y-2">
            {history.map((item) => (
              <li key={item.id} className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {item.student_name ?? tCommon("states.unknown")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {item.bed_label ?? t("bed")}
                      {item.room_number ? ` · ${t("roomNumber", { number: item.room_number })}` : ""}
                    </p>
                  </div>
                  <StatusBadge tone={toneForStatus(item.status)}>
                    {statusLabel(item.status, "housing.assignmentStatus")}
                  </StatusBadge>
                </div>
                <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <dt className="text-muted-foreground">{t("startDate")}</dt>
                    <dd>{format.dateTime(new Date(item.start_date), { dateStyle: "medium" })}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("endDate")}</dt>
                    <dd>
                      {item.end_date
                        ? format.dateTime(new Date(item.end_date), { dateStyle: "medium" })
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("createdBy")}</dt>
                    <dd>{item.created_by_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">{t("endedBy")}</dt>
                    <dd>{item.ended_by_name ?? "—"}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </section>
    </AppShell>
  );
}
