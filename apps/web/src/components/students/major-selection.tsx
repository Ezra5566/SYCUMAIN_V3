"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { studentApi } from "@/lib/student-api";
import { listPeriods, listProgramOfferings } from "@/lib/academic-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/components/ui/filter-select";
import { LoadingState } from "@/components/ui/loading-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { toast } from "@/components/ui/toast";

/**
 * A student declaring their intake-specific program offering.
 *
 * The source catalogue is authoritative: an offering is selectable only when
 * the API marks it as mapped to an active canonical program and open intake.
 * The old major/program pair is not used here because it is not the hierarchy
 * the institution actually enrolls students through.
 */
export function MajorSelection({ onSelected }: { onSelected: () => Promise<void> | void }) {
  const t = useTranslations("studentProfile");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [periodId, setPeriodId] = useState("");
  const [offeringId, setOfferingId] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const placement = useApi(() => studentApi.getOwnPlacement(), [], "placement status");
  const periods = useApi(() => listPeriods(1, 100), [], "intake periods");
  const fetchOfferings = useCallback(
    () =>
      periodId
        ? listProgramOfferings(periodId, undefined, 1, 100)
        : Promise.resolve(null),
    [periodId],
  );
  const offerings = useApi(fetchOfferings, [periodId], "program offerings");

  if (placement.loading || periods.loading) return <LoadingState />;

  if (placement.error) {
    const localized = localizeError(placement.error);
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          {localized.message}
        </CardContent>
      </Card>
    );
  }

  const status = placement.data;
  if (!status) return null;

  const hasPlacement = Boolean(
    status.program_offering_id || status.program_id || status.major_id,
  );

  const activePeriods = (periods.data?.items ?? []).filter(
    (period) => period.status === "ACTIVE" || period.status === "PLANNED",
  );
  const offeringOptions = (offerings.data?.items ?? [])
    .filter((offering) => offering.selectable !== false)
    .map((offering) => ({ value: offering.id, label: offering.name }));

  // A confirmed placement is read-only here by design.
  if (!status.can_select) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("myAcademic")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {hasPlacement && (
            <StatusBadge tone="neutral">{t("placementConfirmed")}</StatusBadge>
          )}
          <p className="text-sm font-medium">
            {status.program_offering_name ??
              status.program_name ??
              status.major_name ??
              tCommon("states.notSet")}
          </p>
          {(status.program_offering_period_name || status.program_name) && (
            <p className="text-sm text-muted-foreground">
              {status.program_offering_period_name ?? status.program_name}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            {hasPlacement
              ? t("placementContactOffice")
              : t("placementManagedByOffice")}
          </p>
        </CardContent>
      </Card>
    );
  }

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      await studentApi.selectOwnPlacement({
        program_offering_id: offeringId,
      });
      toast.success(t("majorSelected"));
      await placement.refetch();
      await onSelected();
    } catch (error) {
      setFailure(normalizeApiError(error, "academic"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("chooseMajor")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <FilterSelect
          label={t("intakePeriod")}
          value={periodId}
          showLabel
          options={[
            { value: "", label: tCommon("labels.selectPlaceholder") },
            ...activePeriods.map((period) => ({
              value: period.id,
              label: `${period.name} (${period.code})`,
            })),
          ]}
          onChange={(value) => {
            setPeriodId(value);
            setOfferingId("");
          }}
        />

        <FilterSelect
          label={t("programOffering")}
          value={offeringId}
          showLabel
          options={[
            {
              value: "",
              label: offerings.loading
                ? tCommon("states.loading")
                : tCommon("labels.selectPlaceholder"),
            },
            ...offeringOptions,
          ]}
          onChange={setOfferingId}
        />

        {periodId && !offerings.loading && offeringOptions.length === 0 && (
          <p className="text-xs text-muted-foreground">{t("noOfferings")}</p>
        )}
        <p className="text-xs text-muted-foreground">{t("majorSelectHint")}</p>

        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}

        <Button onClick={() => void submit()} disabled={busy || offeringId === ""}>
          {busy ? tCommon("states.saving") : tCommon("actions.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
