"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarRange, History } from "lucide-react";
import {
  correctPeriodDates,
  listPeriodDateCorrections,
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
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import type {
  AcademicPeriod,
  AcademicPeriodDateCorrection,
} from "@/types/academic";

function dateOnly(value: string) {
  return new Date(`${value}T00:00:00`);
}

/**
 * Controlled intake-date correction (Phase 5).
 *
 * Dates are edited here, never in the ordinary period form once dependants
 * exist. The dialog shows the previous dates, requires both new dates and a
 * substantial reason, and keeps the append-only correction history visible so
 * a reversal is another recorded correction rather than a silent edit.
 */
export function PeriodCorrectionDialog({
  period,
  onSaved,
}: {
  period: AcademicPeriod;
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("academics.periodCorrection");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();

  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(period.start_date);
  const [end, setEnd] = useState(period.end_date);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [history, setHistory] = useState<AcademicPeriodDateCorrection[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [validation, setValidation] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      setHistory(await listPeriodDateCorrections(period.id));
    } catch (error) {
      setFailure(normalizeApiError(error, "period correction history"));
    } finally {
      setLoadingHistory(false);
    }
  }, [period.id]);

  useEffect(() => {
    if (!open) return;
    setStart(period.start_date);
    setEnd(period.end_date);
    setReason("");
    setEvidence("");
    setFailure(null);
    setValidation(null);
    void loadHistory();
  }, [open, period.start_date, period.end_date, loadHistory]);

  async function submit() {
    setFailure(null);
    setValidation(null);
    if (reason.trim().length < 20) {
      setValidation(t("reasonTooShort"));
      return;
    }
    if (end < start) {
      setValidation(t("invalidRange"));
      return;
    }
    if (start === period.start_date && end === period.end_date) {
      setValidation(t("unchanged"));
      return;
    }

    setBusy(true);
    try {
      const correction = await correctPeriodDates(period.id, {
        new_start_date: start,
        new_end_date: end,
        reason: reason.trim(),
        evidence_reference: evidence.trim() || null,
      });
      toast.success(t("success"));
      setStart(correction.new_start_date);
      setEnd(correction.new_end_date);
      setReason("");
      setEvidence("");
      await loadHistory();
      await onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "correct period dates"));
    } finally {
      setBusy(false);
    }
  }

  const localized = localizeError(failure);

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <CalendarRange className="h-3.5 w-3.5" aria-hidden="true" />
        {t("action")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>
              <span className="block font-mono text-xs text-muted-foreground">
                {period.code}
              </span>
              {t("description")}
            </DialogDescription>
          </DialogHeader>

          {period.status === "COMPLETED" && (
            <p className="rounded-md border border-warning/40 bg-warning-soft/40 p-3 text-sm text-warning">
              {t("completedNotice")}
            </p>
          )}

          <div className="rounded-lg border border-border/80 bg-muted/35 p-3 text-sm">
            <p className="font-medium">{t("currentDates")}</p>
            <p className="mt-1 tabular-nums text-muted-foreground">
              {format.dateTime(dateOnly(period.start_date), {
                dateStyle: "medium",
              })}{" "}
              –{" "}
              {format.dateTime(dateOnly(period.end_date), {
                dateStyle: "medium",
              })}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("newStartDate")}</span>
              <Input
                type="date"
                value={start}
                required
                disabled={busy}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("newEndDate")}</span>
              <Input
                type="date"
                value={end}
                required
                disabled={busy}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
          </div>

          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("reason")}</span>
            <Textarea
              value={reason}
              required
              minLength={20}
              rows={3}
              disabled={busy}
              placeholder={t("reasonHint")}
              onChange={(event) => setReason(event.target.value)}
            />
            <span className="block text-xs text-muted-foreground">
              {t("reasonRule")}
            </span>
          </label>

          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("evidenceReference")}</span>
            <Input
              value={evidence}
              maxLength={500}
              disabled={busy}
              placeholder={t("evidenceHint")}
              onChange={(event) => setEvidence(event.target.value)}
            />
          </label>

          {(validation || failure) && (
            <div
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
            >
              <p className="font-medium">
                {validation ?? localized.message}
              </p>
              {!validation && localized.hint && (
                <p className="mt-1 text-xs">{localized.hint}</p>
              )}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {tCommon("actions.cancel")}
            </Button>
            <Button type="button" disabled={busy} onClick={() => void submit()}>
              {busy ? t("saving") : t("submit")}
            </Button>
          </DialogFooter>

          <section className="space-y-2 border-t pt-4">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <History className="h-4 w-4" aria-hidden="true" />
              {t("historyTitle")}
            </h3>
            <p className="text-xs text-muted-foreground">{t("historyHint")}</p>

            {loadingHistory ? (
              <p className="text-sm text-muted-foreground">
                {tCommon("states.loading")}
              </p>
            ) : history.length === 0 ? (
              <EmptyState title={t("historyEmpty")} />
            ) : (
              <ol className="space-y-2">
                {history.map((entry) => (
                  <li
                    key={entry.id}
                    className="rounded-lg border border-border/80 bg-card p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="font-medium tabular-nums">
                        {format.dateTime(dateOnly(entry.previous_start_date), {
                          dateStyle: "medium",
                        })}{" "}
                        –{" "}
                        {format.dateTime(dateOnly(entry.previous_end_date), {
                          dateStyle: "medium",
                        })}{" "}
                        <span aria-hidden="true">→</span>{" "}
                        {format.dateTime(dateOnly(entry.new_start_date), {
                          dateStyle: "medium",
                        })}{" "}
                        –{" "}
                        {format.dateTime(dateOnly(entry.new_end_date), {
                          dateStyle: "medium",
                        })}
                      </p>
                      <time
                        className="text-xs tabular-nums text-muted-foreground"
                        dateTime={entry.created_at}
                      >
                        {format.dateTime(new Date(entry.created_at), {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}
                      </time>
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      {t("changedBy")}: {entry.actor_name ?? "—"}
                    </p>
                    <p className="mt-2">{entry.reason}</p>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      {t("placementsCount", {
                        count: entry.placements_reflagged,
                      })}{" "}
                      ·{" "}
                      {t("admissionsCount", {
                        count: entry.admissions_rechecked,
                      })}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </DialogContent>
      </Dialog>
    </>
  );
}
