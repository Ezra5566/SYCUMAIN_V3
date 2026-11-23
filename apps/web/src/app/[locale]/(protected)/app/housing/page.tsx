"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import {
  BedDouble,
  Building2,
  CheckCircle2,
  DoorOpen,
  Layers3,
  Users,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { getHousingOverview } from "@/lib/housing-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { occupancyPercent } from "@/lib/occupancy";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { OccupancyLegend } from "@/components/housing/occupancy-legend";
import { BuildingRoomMap } from "@/components/housing/building-room-map";
import { AddBuildingDialog } from "@/components/housing/structure-dialogs";
import { useAuth } from "@/lib/auth-context";
import type { HousingOverviewResponse } from "@/types/housing";

export default function HousingPage() {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const { hasPermission } = useAuth();

  const fetchOverview = useCallback(() => getHousingOverview(), []);
  const { data, loading, error, refetch } = useApi<HousingOverviewResponse>(
    fetchOverview,
    [],
    "housing overview",
  );

  const localized = localizeError(error);

  if (loading) {
    return (
      <AppShell>
        <LoadingState />
      </AppShell>
    );
  }

  if (error) {
    return (
      <AppShell>
        <ErrorState
          message={localized.message}
          hint={localized.hint}
          status={error.status}
          onRetry={refetch}
        />
      </AppShell>
    );
  }

  const buildings = data?.buildings ?? [];
  const totals = buildings.reduce(
    (acc, building) => ({
      rooms: acc.rooms + building.room_count,
      beds: acc.beds + building.bed_count,
      occupied: acc.occupied + building.occupied_count,
      available: acc.available + building.available_count,
    }),
    { rooms: 0, beds: 0, occupied: 0, available: 0 },
  );
  const totalOccupied = data?.total_occupied ?? totals.occupied;
  const totalBeds = data?.total_beds ?? totals.beds;
  const totalAvailable = data?.total_available ?? totals.available;
  const totalRooms = data?.total_rooms ?? totals.rooms;
  const pct = occupancyPercent(totalOccupied, totalBeds);
  const availablePct = occupancyPercent(totalAvailable, totalBeds);

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          hasPermission("housing.create") ? (
            <AddBuildingDialog onCreated={refetch} />
          ) : undefined
        }
      />

      <Card className="mb-4 overflow-hidden">
        <div className="grid lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="relative overflow-hidden border-e border-border bg-muted/40 p-5 sm:p-6">
            <div className="institutional-contours absolute inset-0 opacity-70" aria-hidden="true" />
            <div className="relative">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-gold">
                {t("occupancyEyebrow")}
              </p>
              <div className="mt-3 flex items-end gap-3">
                <p className="text-[3.2rem] font-semibold leading-none tracking-[-0.06em] tabular-nums">
                  {pct}
                  <span className="ms-0.5 text-2xl">%</span>
                </p>
                <p className="mb-1.5 text-xs leading-relaxed text-muted-foreground">
                  {totalOccupied} / {totalBeds}
                  <br />
                  {tCommon("counts.beds", { count: totalBeds })}
                </p>
              </div>
              <div
                className="mt-5 flex h-3 overflow-hidden rounded-full bg-muted ring-1 ring-inset ring-border"
                role="img"
                aria-label={`${t("occupancy")}: ${pct}%`}
              >
                <span className="h-full bg-gold" style={{ width: `${pct}%` }} />
                <span className="h-full bg-success/80" style={{ width: `${availablePct}%` }} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-gold" aria-hidden="true" />
                  {t("occupied")} {totalOccupied}
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-success/80" aria-hidden="true" />
                  {t("available")} {totalAvailable}
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-px bg-border/80">
            {[
              {
                label: t("buildings"),
                value: buildings.length,
                hint: t("buildingsHint"),
                icon: Building2,
              },
              {
                label: t("rooms"),
                value: totalRooms,
                hint: t("roomsHint"),
                icon: DoorOpen,
              },
              {
                label: t("beds"),
                value: totalBeds,
                hint: t("bedsHint"),
                icon: BedDouble,
              },
              {
                label: t("available"),
                value: totalAvailable,
                hint: t("availableHint"),
                icon: CheckCircle2,
                tone: "text-success",
              },
            ].map(({ label, value, hint, icon: Icon, tone }) => (
              <div key={label} className="min-w-0 bg-card p-4 sm:p-5">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {label}
                  </p>
                  <Icon className={cn("h-4 w-4 shrink-0 text-muted-foreground", tone)} aria-hidden="true" />
                </div>
                <p className={cn("mt-3 text-2xl font-semibold leading-none tabular-nums", tone)}>
                  {value}
                </p>
                <p className="mt-1.5 text-[10px] text-muted-foreground">{hint}</p>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <OccupancyLegend />
        <p className="text-xs text-muted-foreground">{t("roomGridHint")}</p>
      </div>

      {buildings.length === 0 ? (
        <Card>
          <CardContent className="pt-6">
            <EmptyState title={t("noBuildings")} />
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {buildings.map((building) => {
            const buildingPct = occupancyPercent(
              building.occupied_count,
              building.bed_count,
            );
            const statusText = statusLabel(
              building.occupancy_status,
              "housing.occupancyStatus",
            );

            return (
              <Link
                key={building.id}
                href={`/app/housing/${building.id}`}
                className="group block h-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Card className="flex h-full flex-col overflow-hidden transition-[border-color,box-shadow,transform] duration-150 group-hover:-translate-y-0.5 group-hover:border-primary/25 group-hover:shadow-raised">
                  <div className="relative h-[5.4rem] overflow-hidden border-b border-border bg-muted/40 px-4 py-3.5">
                    <div className="institutional-grid absolute inset-0 opacity-50" aria-hidden="true" />
                    <Building2
                      className="absolute -bottom-6 end-2 h-24 w-24 text-foreground/[0.055]"
                      aria-hidden="true"
                    />
                    <div className="relative flex h-full flex-col justify-between">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-card/70 text-gold">
                            <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </span>
                          <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                            {t("building")}
                          </p>
                        </div>
                        <StatusBadge tone={toneForStatus(building.occupancy_status)}>
                          {statusText}
                        </StatusBadge>
                      </div>
                      <div className="flex items-end justify-between gap-3">
                        <CardTitle className="truncate text-lg text-foreground">
                          {building.name}
                        </CardTitle>
                        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                          {building.floor_count} {t("floors")}
                        </span>
                      </div>
                    </div>
                  </div>

                  <CardContent className="flex flex-1 flex-col gap-4 p-4">
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-muted-foreground">{t("floors")}</dt>
                        <dd className="font-medium tabular-nums">{building.floor_count}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-muted-foreground">{t("rooms")}</dt>
                        <dd className="font-medium tabular-nums">{building.room_count}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-muted-foreground">{t("beds")}</dt>
                        <dd className="font-medium tabular-nums">{building.bed_count}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-muted-foreground">{t("available")}</dt>
                        <dd className="font-medium tabular-nums text-success">
                          {building.available_count}
                        </dd>
                      </div>
                    </dl>

                    <div>
                      <div className="mb-1.5 flex justify-between gap-2 text-[10px] text-muted-foreground">
                        <span className="flex items-center gap-1.5">
                          <Users className="h-3 w-3" aria-hidden="true" />
                          {building.occupied_count}/{building.bed_count}
                        </span>
                        <span className="font-medium tabular-nums">{buildingPct}%</span>
                      </div>
                      <div
                        className="h-1.5 overflow-hidden rounded-full bg-muted"
                        role="img"
                        aria-label={t("buildingOccupancyLabel", {
                          building: building.name,
                          percent: buildingPct,
                        })}
                      >
                        <div
                          className={cn(
                            "h-full rounded-full",
                            buildingPct >= 100
                              ? "bg-destructive"
                              : buildingPct >= 80
                                ? "bg-warning"
                                : "bg-primary",
                          )}
                          style={{ width: `${buildingPct}%` }}
                        />
                      </div>
                    </div>

                    <div className="mt-auto">
                      <BuildingRoomMap
                        floors={building.floors}
                        buildingName={building.name}
                      />
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </AppShell>
  );
}
