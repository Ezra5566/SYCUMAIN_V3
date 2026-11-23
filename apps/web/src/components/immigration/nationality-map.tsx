"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Globe2, Info, MapPin } from "lucide-react";
import countries, { VIEW_BOX } from "world-map-country-shapes";
import { getNationalityDistribution } from "@/lib/immigration-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const COUNTRY_SHAPES = countries;

/**
 * Aggregated nationality map.
 *
 * Only country totals reach the browser. The SVG is bundled locally, so the
 * visualization makes no external map or geocoding request and no student
 * location, name or document is involved. The ranked list is the accessible
 * textual equivalent of the map, not an afterthought.
 */
export function NationalityMap({
  intakeFilter,
  onIntakeFilterChange,
  periods,
}: {
  intakeFilter: string;
  onIntakeFilterChange: (value: string) => void;
  periods: Array<{ id: string; name: string }>;
}) {
  const t = useTranslations("immigration.map");
  const tCohort = useTranslations("immigration.cohort");
  const locale = useLocale();
  const localizeError = useErrorMessage();
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  const { data, loading, error, refetch } = useApi(
    () => getNationalityDistribution(intakeFilter || undefined),
    [intakeFilter],
    "nationality distribution",
  );

  const regionNames = useMemo(() => {
    try {
      return new Intl.DisplayNames([locale], { type: "region" });
    } catch {
      return null;
    }
  }, [locale]);

  const countryName = (code: string) => regionNames?.of(code) ?? code;
  const countByCode = useMemo(
    () => new Map((data?.countries ?? []).map((country) => [country.code, country.count])),
    [data],
  );
  const maxCount = useMemo(
    () => Math.max(1, ...(data?.countries ?? []).map((country) => country.count)),
    [data],
  );
  const mappedTotal = data?.mapped_students ?? 0;
  const unknownTotal =
    (data?.missing_country_count ?? 0) + (data?.unmapped_country_count ?? 0);
  const selectedCount = selected ? (countByCode.get(selected) ?? 0) : 0;
  const activeCode = hovered ?? selected;
  const activeCount = activeCode ? (countByCode.get(activeCode) ?? 0) : 0;

  const fillFor = (count: number) => {
    if (count <= 0) return "hsl(var(--muted)) ";
    const ratio = count / maxCount;
    return `hsl(var(--primary) / ${(0.22 + ratio * 0.68).toFixed(2)})`;
  };

  const localized = localizeError(error);

  return (
    <Card className="mb-4 overflow-hidden">
      <CardHeader className="flex flex-col gap-3 border-b border-border/70 bg-muted/20 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe2 className="h-4 w-4 text-primary" aria-hidden="true" />
            {t("title")}
          </CardTitle>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">
            {t("subtitle")}
          </p>
        </div>
        <div className="w-full sm:w-56">
          <FilterSelect
            label={tCohort("filterIntakeMap")}
            value={intakeFilter}
            options={[
              { value: "", label: tCohort("allIntakes") },
              ...periods.map((period) => ({ value: period.id, label: period.name })),
            ]}
            onChange={onIntakeFilterChange}
          />
        </div>
      </CardHeader>

      <CardContent className="pt-4">
        {error ? (
          <ErrorState message={localized.message} hint={localized.hint} onRetry={refetch} />
        ) : loading || !data ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <Skeleton className="h-64 rounded-xl" />
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((item) => (
                <Skeleton key={item} className="h-8 rounded-md" />
              ))}
            </div>
          </div>
        ) : data.total_students === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-muted/15 px-5 py-12 text-center">
            <Globe2 className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium">{t("noData")}</p>
            <p className="mt-1 max-w-sm text-xs text-muted-foreground">{t("noDataHint")}</p>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <div className="min-w-0">
              <div className="relative overflow-hidden rounded-xl border border-border/70 bg-gradient-to-b from-muted/25 to-background">
                <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border bg-card/95 px-2.5 py-1.5 text-[11px] shadow-sm">
                  {activeCode ? (
                    <>
                      <span className="block font-semibold">{countryName(activeCode)}</span>
                      <span className="text-muted-foreground">
                        {t("studentsCount", { count: activeCount })}
                      </span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">{t("hoverHint")}</span>
                  )}
                </div>
                <svg
                  viewBox={VIEW_BOX}
                  role="group"
                  aria-label={t("mapLabel")}
                  className="block h-auto w-full"
                >
                  {COUNTRY_SHAPES.map((country) => {
                    const count = countByCode.get(country.id) ?? 0;
                    const isSelected = selected === country.id;
                    return (
                      <path
                        key={country.id}
                        d={country.shape}
                        fill={fillFor(count)}
                        stroke={isSelected ? "hsl(var(--gold))" : "hsl(var(--border))"}
                        strokeWidth={isSelected ? 3 : 0.7}
                        vectorEffect="non-scaling-stroke"
                        tabIndex={count > 0 ? 0 : undefined}
                        role={count > 0 ? "button" : undefined}
                        aria-label={
                          count > 0
                            ? `${countryName(country.id)}: ${t("studentsCount", { count })}`
                            : undefined
                        }
                        aria-pressed={count > 0 ? isSelected : undefined}
                        className={cn(
                          "transition-[fill,stroke] duration-150",
                          count > 0
                            ? "cursor-pointer hover:stroke-primary focus-visible:stroke-gold focus-visible:outline-none"
                            : "pointer-events-none",
                        )}
                        onMouseEnter={() => count > 0 && setHovered(country.id)}
                        onMouseLeave={() => setHovered(null)}
                        onFocus={() => count > 0 && setHovered(country.id)}
                        onBlur={() => setHovered(null)}
                        onClick={() =>
                          count > 0 && setSelected((code) => (code === country.id ? null : country.id))
                        }
                        onKeyDown={(event) => {
                          if (count > 0 && (event.key === "Enter" || event.key === " ")) {
                            event.preventDefault();
                            setSelected((code) =>
                              code === country.id ? null : country.id,
                            );
                          }
                        }}
                      >
                        <title>
                          {countryName(country.id)}
                          {count > 0 ? ` · ${t("studentsCount", { count })}` : ""}
                        </title>
                      </path>
                    );
                  })}
                </svg>
              </div>

              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("total")}
                  </p>
                  <p className="mt-1 text-xl font-semibold tabular-nums">
                    {data.total_students}
                  </p>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("mapped")}
                  </p>
                  <p className="mt-1 text-xl font-semibold tabular-nums">{mappedTotal}</p>
                </div>
                <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("countries")}
                  </p>
                  <p className="mt-1 text-xl font-semibold tabular-nums">
                    {data.countries.length}
                  </p>
                </div>
              </div>

              {unknownTotal > 0 && (
                <div className="mt-2 flex items-start gap-2 rounded-lg border border-border/70 bg-muted/20 p-3 text-xs">
                  <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <div>
                    <p className="font-medium">{t("unknownTitle", { count: unknownTotal })}</p>
                    <p className="mt-0.5 text-muted-foreground">
                      {t("unknownBreakdown", {
                        missing: data.missing_country_count,
                        unmapped: data.unmapped_country_count,
                      })}
                    </p>
                  </div>
                </div>
              )}

              {mappedTotal === 0 && (
                <p className="mt-2 rounded-lg border border-dashed border-border/80 p-3 text-xs text-muted-foreground">
                  {t("noMapped")}
                </p>
              )}
            </div>

            <div className="min-w-0">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("ranked")}
                </p>
                {selected && (
                  <button
                    type="button"
                    onClick={() => setSelected(null)}
                    className="rounded-sm text-[11px] font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {t("clearSelection")}
                  </button>
                )}
              </div>
              <ol className="mt-2 max-h-[22rem] space-y-1 overflow-y-auto pr-1">
                {(data.countries ?? []).map((country, index) => {
                  const isSelected = selected === country.code;
                  return (
                    <li key={country.code}>
                      <button
                        type="button"
                        onClick={() =>
                          setSelected((code) =>
                            code === country.code ? null : country.code,
                          )
                        }
                        aria-pressed={isSelected}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isSelected ? "bg-primary/10" : "hover:bg-muted/60",
                        )}
                      >
                        <span className="w-4 shrink-0 text-[10px] tabular-nums text-muted-foreground">
                          {index + 1}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-xs font-medium">
                          {countryName(country.code)}
                        </span>
                        <span className="relative h-1.5 w-16 shrink-0 overflow-hidden rounded-full bg-muted">
                          <span
                            className="absolute inset-y-0 start-0 rounded-full bg-primary"
                            style={{ width: `${(country.count / maxCount) * 100}%` }}
                          />
                        </span>
                        <span className="w-6 shrink-0 text-end text-xs font-semibold tabular-nums">
                          {country.count}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              {selected && (
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/[0.045] p-3">
                  <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                  <div>
                    <p className="text-xs font-semibold">{countryName(selected)}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {t("selectedDetail", {
                        count: selectedCount,
                        total: data.total_students,
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}