"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, FileJson, RotateCcw, Upload } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { useAuth } from "@/lib/auth-context";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import {
  applyAcademicImport,
  listAcademicImports,
  listPeriods,
  previewAcademicImport,
  rollbackAcademicImport,
} from "@/lib/academic-api";
import type {
  AcademicImportBatchReport,
  AcademicPeriod,
} from "@/types/academic";

/**
 * Source-catalogue import console.
 *
 * The importer already existed as a staged service but had no way in. This page
 * is that way in, and only that: preview stages the catalogue, apply writes the
 * rows after an explicit confirmation, rollback removes the batch's own rows.
 * Every mapping is chosen here and nothing is inferred from a name.
 *
 * Access is `academic.manage_periods` on the API; the same permission decides
 * whether this page renders its controls at all. A hidden button is not the
 * control — the API rejects a teacher or student regardless.
 */
export default function AcademicImportPage() {
  const t = useTranslations("academicImport");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();

  const canManage = hasPermission("academic.manage_periods");

  const periodsApi = useApi(() => listPeriods(1, 100), [], "academic periods");
  const batchesApi = useApi(() => listAcademicImports(), [], "academic imports");
  const periods: AcademicPeriod[] = useMemo(
    () => periodsApi.data?.items ?? [],
    [periodsApi.data],
  );

  const [report, setReport] = useState<AcademicImportBatchReport | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  /**
   * Suggest a period for a source semester from its dates, not its name.
   * A source semester is `2026-autumn`; a period carries real start/end dates,
   * so year + half-year is a fact we can check. The suggestion is only a
   * default in a visible select and can be changed or cleared.
   */
  const suggestedPeriod = useCallback(
    (sourceId: string): string => {
      const match = /^(\d{4})-(spring|autumn)$/.exec(sourceId);
      if (!match) return "";
      const year = Number(match[1]);
      const autumn = match[2] === "autumn";
      const candidate = periods.find((period) => {
        const start = new Date(period.start_date);
        if (start.getFullYear() !== year) return false;
        return autumn ? start.getMonth() >= 6 : start.getMonth() <= 5;
      });
      return candidate?.id ?? "";
    },
    [periods],
  );

  useEffect(() => {
    if (!report) return;
    setMapping((current) => {
      if (Object.keys(current).length > 0) return current;
      const next: Record<string, string> = {};
      for (const period of report.periods) {
        next[period.source_id] = suggestedPeriod(period.source_id);
      }
      return next;
    });
  }, [report, suggestedPeriod]);

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    setConfirmed(false);
    try {
      const staged = await previewAcademicImport();
      setReport(staged);
      setMapping({});
      batchesApi.refetch();
      if (staged.already_applied) setNotice(t("alreadyAppliedNotice"));
    } catch (err) {
      setError(normalizeApiError(err, "academic import preview"));
    } finally {
      setBusy(false);
    }
  };

  const runApply = async () => {
    if (!report || !confirmed) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const periodMap: Record<string, string> = {};
      for (const [sourceId, periodId] of Object.entries(mapping)) {
        if (periodId) periodMap[sourceId] = periodId;
      }
      const applied = await applyAcademicImport(report.batch_id, periodMap);
      setReport(applied);
      setConfirmed(false);
      setNotice(t("appliedNotice"));
      batchesApi.refetch();
    } catch (err) {
      setError(normalizeApiError(err, "academic import apply"));
    } finally {
      setBusy(false);
    }
  };

  const runRollback = async (batchId: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await rollbackAcademicImport(batchId);
      setNotice(t("rolledBackNotice"));
      if (report?.batch_id === batchId) {
        setReport(null);
        setMapping({});
      }
      batchesApi.refetch();
    } catch (err) {
      setError(normalizeApiError(err, "academic import rollback"));
    } finally {
      setBusy(false);
    }
  };

  const mappedCount = report
    ? report.periods.filter((period) => mapping[period.source_id]).length
    : 0;
  const hasHeld = (report?.held.length ?? 0) > 0;
  const batches = batchesApi.data ?? [];

  const header = (
    <PageHeader
      title={t("title")}
      description={t("subtitle")}
      breadcrumbs={[
        { label: tCommon("labels.overview"), href: "/app" },
        { label: t("academicsBreadcrumb"), href: "/app/academics" },
        { label: t("title") },
      ]}
    />
  );

  if (!canManage) {
    return (
      <AppShell>
        {header}
        <EmptyState title={t("forbiddenTitle")} message={t("forbiddenHint")} />
      </AppShell>
    );
  }

  return (
    <AppShell>
      {header}

      {error && (
        <div className="mb-4">
          <ErrorState message={localizeError(error).message} hint={localizeError(error).hint} />
        </div>
      )}
      {notice && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-success/30 bg-success-soft px-3 py-2 text-sm text-success">
          <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
          {notice}
        </div>
      )}

      <div className="space-y-4">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3 pb-2">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileJson className="h-4 w-4" aria-hidden="true" />
                {t("dryRunTitle")}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">{t("dryRunHint")}</p>
            </div>
            <Button onClick={runPreview} disabled={busy} className="shrink-0">
              <Upload className="me-1.5 h-4 w-4" aria-hidden="true" />
              {busy ? t("working") : t("runDryRun")}
            </Button>
          </CardHeader>
          <CardContent>
            {periodsApi.loading ? (
              <LoadingState />
            ) : report ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <StatusBadge
                    tone={
                      report.status === "APPLIED"
                        ? "success"
                        : report.status === "FAILED"
                          ? "danger"
                          : "info"
                    }
                  >
                    {t.has(`status.${report.status}`)
                      ? t(`status.${report.status}`)
                      : report.status}
                  </StatusBadge>
                  <span className="font-mono text-xs text-muted-foreground">
                    {report.source_name} · {report.source_sha256.slice(0, 12)}
                  </span>
                </div>

                <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
                  {(
                    [
                      ["periods", report.counts.periods],
                      ["offerings", report.counts.offerings],
                      ["courses", report.counts.courses],
                      ["rooms", report.counts.rooms],
                      ["sections", report.counts.sections],
                      ["sessions", report.counts.sessions],
                    ] as const
                  ).map(([key, value]) => (
                    <div
                      key={key}
                      className="rounded-lg border border-border/70 bg-background/60 px-3 py-2"
                    >
                      <dt className="text-[11px] text-muted-foreground">
                        {t(`entities.${key}`)}
                      </dt>
                      <dd className="text-lg font-semibold tabular-nums">{value ?? 0}</dd>
                    </div>
                  ))}
                </dl>

                {hasHeld && (
                  <div className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
                    <p className="flex items-center gap-1.5 font-medium">
                      <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                      {t("heldTitle", { count: report.held.length })}
                    </p>
                    <p className="mt-1 text-xs opacity-90">{t("heldHint")}</p>
                    <ul className="mt-1.5 max-h-32 space-y-0.5 overflow-auto font-mono text-[11px]">
                      {report.held.slice(0, 20).map((row) => (
                        <li key={`${row.entity_type}-${row.source_key}`}>
                          {row.entity_type} · {row.error_code ?? row.action}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <h3 className="text-sm font-semibold">{t("mappingTitle")}</h3>
                  <p className="mb-2 mt-0.5 text-xs text-muted-foreground">
                    {t("mappingHint")}
                  </p>
                  <div className="space-y-2">
                    {report.periods.map((period) => (
                      <div
                        key={period.source_id}
                        className="flex flex-col gap-2 rounded-lg border border-border/70 bg-background/60 px-3 py-2 sm:flex-row sm:items-center"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium">{period.source_id}</p>
                          <p className="truncate font-mono text-[11px] text-muted-foreground">
                            {period.source_key}
                          </p>
                        </div>
                        <label className="flex items-center gap-2 text-xs">
                          <span className="text-muted-foreground">{t("targetPeriod")}</span>
                          <select
                            className="h-9 min-w-[14rem] rounded-md border border-input bg-background px-3 text-sm"
                            value={mapping[period.source_id] ?? ""}
                            disabled={report.status === "APPLIED"}
                            onChange={(event) =>
                              setMapping((current) => ({
                                ...current,
                                [period.source_id]: event.target.value,
                              }))
                            }
                          >
                            <option value="">{t("leaveUnmapped")}</option>
                            {periods.map((option) => (
                              <option key={option.id} value={option.id}>
                                {option.name} ({option.code})
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                    ))}
                  </div>
                </div>

                {report.status !== "APPLIED" && (
                  <div className="rounded-lg border border-border/70 bg-muted/20 px-3 py-2">
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4"
                        checked={confirmed}
                        onChange={(event) => setConfirmed(event.target.checked)}
                      />
                      <span>{t("confirmLabel")}</span>
                    </label>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button onClick={runApply} disabled={busy || !confirmed}>
                        {busy ? t("working") : t("apply")}
                      </Button>
                      <span className="text-xs text-muted-foreground">
                        {t("mappedCount", {
                          mapped: mappedCount,
                          total: report.periods.length,
                        })}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{t("noPreviewYet")}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{t("batchesTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            {batchesApi.loading ? (
              <LoadingState />
            ) : batchesApi.error ? (
              <ErrorState
                message={localizeError(batchesApi.error).message}
                hint={localizeError(batchesApi.error).hint}
                onRetry={batchesApi.refetch}
              />
            ) : batches.length === 0 ? (
              <EmptyState title={t("noBatches")} message={t("noBatchesHint")} />
            ) : (
              <ul className="divide-y divide-border/70">
                {batches.map((batch) => (
                  <li
                    key={batch.batch_id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2"
                  >
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 text-sm font-medium">
                        <StatusBadge
                          tone={
                            batch.status === "APPLIED"
                              ? "success"
                              : batch.status === "FAILED"
                                ? "danger"
                                : batch.status === "ROLLED_BACK"
                                  ? "neutral"
                                  : "info"
                          }
                        >
                          {t.has(`status.${batch.status}`)
                            ? t(`status.${batch.status}`)
                            : batch.status}
                        </StatusBadge>
                        <span className="truncate">{batch.source_name}</span>
                      </p>
                      <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                        {format.dateTime(new Date(batch.created_at), {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}{" "}
                        · {batch.source_sha256.slice(0, 12)} ·{" "}
                        {t("batchCounts", {
                          sections: batch.counts.sections ?? 0,
                          sessions: batch.counts.sessions ?? 0,
                        })}
                      </p>
                    </div>
                    {batch.status === "APPLIED" && (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        onClick={() => runRollback(batch.batch_id)}
                      >
                        <RotateCcw className="me-1.5 h-3.5 w-3.5" aria-hidden="true" />
                        {t("rollback")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
