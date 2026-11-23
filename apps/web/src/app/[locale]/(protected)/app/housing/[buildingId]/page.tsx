"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Link } from "@/i18n/navigation";
import { getBuilding } from "@/lib/housing-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { occupancyPercent } from "@/lib/occupancy";
import { AppShell } from "@/components/layout/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { Button } from "@/components/ui/button";
import { OccupancyLegend } from "@/components/housing/occupancy-legend";
import { AddFloorDialog } from "@/components/housing/structure-dialogs";
import { useAuth } from "@/lib/auth-context";
import type { BuildingDetail } from "@/types/housing";

export default function BuildingPage() {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const params = useParams<{ buildingId: string }>();
  const buildingId = params?.buildingId ?? "";
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();

  const fetchBuilding = useCallback(() => getBuilding(buildingId), [buildingId]);
  const { hasPermission } = useAuth();
  const { data: building, loading, error, refetch } = useApi<BuildingDetail>(
    fetchBuilding,
    [buildingId],
    "building detail",
  );

  const localized = localizeError(error);

  if (loading) {
    return (
      <AppShell>
        <LoadingState />
      </AppShell>
    );
  }

  if (error || !building) {
    return (
      <AppShell>
        <ErrorState
          title={error?.status === 404 ? tCommon("states.notAvailable") : localized.message}
          message={error?.status === 404 ? undefined : localized.hint}
          onRetry={error?.status === 404 ? undefined : refetch}
        />
        <div className="mt-4 flex justify-center gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href="/app/housing">{t("title")}</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        title={building.name}
        description={t("buildingSummary", {
          floors: building.floor_count,
          rooms: building.room_count,
          beds: building.bed_count,
        })}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title"), href: "/app/housing" },
          { label: building.name },
        ]}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge tone={toneForStatus(building.occupancy_status)}>
              {statusLabel(building.occupancy_status, "housing.occupancyStatus")}
            </StatusBadge>
            {hasPermission("housing.create") && (
              <AddFloorDialog
                buildingId={buildingId}
                nextFloorNumber={
                  building.floors.reduce(
                    (highest, floor) => Math.max(highest, floor.floor_number),
                    0,
                  ) + 1
                }
                onCreated={refetch}
              />
            )}
          </div>
        }
      />

      <StatGrid className="lg:grid-cols-4">
        <StatCard label={t("rooms")} value={building.room_count} />
        <StatCard label={t("beds")} value={building.bed_count} />
        <StatCard label={t("occupied")} value={building.occupied_count} tone="info" />
        <StatCard label={t("available")} value={building.available_count} tone="success" />
      </StatGrid>

      <OccupancyLegend className="mb-4" />

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {t("sectionFloors")}
      </h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {building.floors.map((floor) => {
          const pct = occupancyPercent(floor.occupied_count, floor.bed_count);
          return (
            <Link
              key={floor.id}
              href={`/app/housing/${buildingId}/${floor.id}`}
              className="group rounded-lg border bg-background transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Card className="h-full border-0 shadow-none">
                <CardContent className="space-y-3 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">
                      {t("floorNumber", { number: floor.floor_number })}
                    </span>
                    <StatusBadge tone={toneForStatus(floor.occupancy_status)}>
                      {statusLabel(floor.occupancy_status, "housing.occupancyStatus")}
                    </StatusBadge>
                  </div>

                  <dl className="grid grid-cols-3 gap-2 text-sm">
                    <div>
                      <dt className="text-xs text-muted-foreground">{t("rooms")}</dt>
                      <dd className="font-medium tabular-nums">{floor.room_count}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">{t("occupied")}</dt>
                      <dd className="font-medium tabular-nums">{floor.occupied_count}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">{t("available")}</dt>
                      <dd className="font-medium tabular-nums text-green-700 dark:text-green-400">
                        {floor.available_count}
                      </dd>
                    </div>
                  </dl>

                  <div
                    className="h-2 overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={t("floorOccupancyLabel", {
                      floor: floor.floor_number,
                      percent: pct,
                    })}
                  >
                    <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </AppShell>
  );
}
