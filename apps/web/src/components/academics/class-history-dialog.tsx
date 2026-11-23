"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { History } from "lucide-react";
import { getClassRecordHistory } from "@/lib/academic-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import type { AcademicChangeHistory } from "@/types/academic";

interface ClassHistoryDialogProps {
  classId: string;
  classLabel: string;
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * Read-only view of append-only academic changes. The API requires
 * `academic.manage_classes`, so the trigger is only rendered by callers that
 * already hold it — this component never widens access.
 */
export function ClassHistoryDialog({ classId, classLabel }: ClassHistoryDialogProps) {
  const t = useTranslations("academics.history");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);

  const { data, loading, error, refetch } = useApi<AcademicChangeHistory[]>(
    () => (open ? getClassRecordHistory(classId) : Promise.resolve([])),
    [open, classId],
    "class record history",
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          {t("title")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[82vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            <span className="block font-mono text-xs text-muted-foreground">{classLabel}</span>
            {t("hint")}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState
            message={localizeError(error).message}
            hint={localizeError(error).hint}
            onRetry={refetch}
          />
        ) : !data || data.length === 0 ? (
          <EmptyState title={t("empty")} />
        ) : (
          <ol className="relative ms-1 space-y-3 border-s border-border/80 ps-5">
            {data.map((entry) => (
              <li
                key={entry.id}
                className="relative rounded-xl border border-border/80 bg-card p-3.5 shadow-card"
              >
                <span
                  className="absolute -start-[1.63rem] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary"
                  aria-hidden="true"
                />
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">
                      {entry.entity_type === "ASSESSMENT"
                        ? t("assessment")
                        : entry.entity_type === "GRADE"
                          ? t("grade")
                          : entry.entity_type.replace(/_/g, " ")}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {t("changedBy")}: {entry.changed_by_name ?? "—"}
                    </p>
                  </div>
                  <time
                    className="text-xs tabular-nums text-muted-foreground"
                    dateTime={entry.changed_at}
                  >
                    {format.dateTime(new Date(entry.changed_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </time>
                </div>

                <dl className="mt-3 space-y-1.5 rounded-lg bg-muted/45 p-2.5 text-xs">
                  {entry.changed_fields.map((field) => (
                    <div key={field} className="flex flex-wrap gap-1">
                      <dt className="font-semibold">{field}:</dt>
                      <dd className="text-muted-foreground">
                        {t("previous")} {displayValue(entry.previous_data?.[field])} →{" "}
                        {t("next")} {displayValue(entry.new_data?.[field])}
                      </dd>
                    </div>
                  ))}
                </dl>

                {entry.reason && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {tCommon("labels.notes")}: {entry.reason}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}
