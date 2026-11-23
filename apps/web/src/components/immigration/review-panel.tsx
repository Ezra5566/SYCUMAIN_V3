"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, ClipboardCheck, X } from "lucide-react";
import {
  approveChangeRequest,
  listChangeRequests,
  rejectChangeRequest,
} from "@/lib/immigration-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import type { ImmigrationChangeRequest } from "@/types/immigration";

/** Pending student submissions, with explicit approve/reject actions. */
export function ImmigrationReviewPanel({
  onReviewed,
}: {
  onReviewed: () => Promise<void> | void;
}) {
  const t = useTranslations("institutional");
  const tImmigration = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const fetchPending = useCallback(() => listChangeRequests("PENDING"), []);
  const { data, loading, error, refetch } = useApi(
    fetchPending,
    [],
    "pending immigration requests",
  );

  const done = async () => {
    await refetch();
    await onReviewed();
  };

  const localized = localizeError(error);

  return (
    <Card className="mb-6">
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <ClipboardCheck className="h-4 w-4 text-primary" aria-hidden="true" />
            {t("pendingChangeRequests")}
          </CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("pendingChangeRequestsDescription")}
          </p>
        </div>
        {data && data.length > 0 && (
          <StatusBadge tone="warning">
            {tImmigration("pendingReviewCount", { count: data.length })}
          </StatusBadge>
        )}
      </CardHeader>
      <CardContent className="pt-0">
        {loading ? (
          <p className="text-sm text-muted-foreground">{tCommon("states.loading")}</p>
        ) : error ? (
          <p className="text-sm text-destructive">{localized.message}</p>
        ) : !data || data.length === 0 ? (
          <EmptyState title={tImmigration("noPendingRequests")} />
        ) : (
          <ul className="divide-y rounded-lg border">
            {data.map((request) => (
              <RequestRow key={request.id} request={request} onDone={done} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RequestRow({
  request,
  onDone,
}: {
  request: ImmigrationChangeRequest;
  onDone: () => Promise<void>;
}) {
  const t = useTranslations("institutional");
  const tImmigration = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function reject() {
    setBusy(true);
    setFailure(null);
    try {
      await rejectChangeRequest(request.id, reason.trim());
      toast.success(tImmigration("rejectSucceeded"));
      setRejecting(false);
      setReason("");
      await onDone();
    } catch (error) {
      setFailure(normalizeApiError(error, "reject immigration request"));
    } finally {
      setBusy(false);
    }
  }

  const entries = Object.entries(request.proposed_data ?? {});

  return (
    <li className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">
            {request.student_name ?? tImmigration("profile")}
          </p>
          <p className="text-xs text-muted-foreground">
            {request.submitter_name
              ? `${tImmigration("submittedBy")}: ${request.submitter_name}`
              : request.change_type}
          </p>
        </div>
        <StatusBadge tone="warning">
          {tImmigration(`requestStatus.${request.status}`)}
        </StatusBadge>
      </div>

      <dl className="grid gap-2 rounded-md bg-muted/25 p-3 text-xs sm:grid-cols-2">
        {entries.map(([field, value]) => (
          <div key={field} className="min-w-0">
            <dt className="font-medium text-muted-foreground">{field}</dt>
            <dd className="break-words">{value === null ? "—" : String(value)}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap justify-end gap-2">
        <ConfirmDialog
          title={tImmigration("approveConfirmTitle")}
          description={tImmigration("approveConfirmBody")}
          confirmLabel={tImmigration("approveRequest")}
          triggerLabel={tImmigration("approveRequest")}
          triggerIcon={<Check className="h-4 w-4" aria-hidden="true" />}
          onConfirm={async () => {
            await approveChangeRequest(request.id);
            toast.success(tImmigration("reviewSucceeded"));
            await onDone();
          }}
        />
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRejecting(true)}
        >
          <X className="me-1 h-4 w-4" aria-hidden="true" />
          {tImmigration("rejectRequest")}
        </Button>
      </div>

      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {localizeError(failure).message}
        </p>
      )}

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{tImmigration("rejectConfirmTitle")}</DialogTitle>
            <DialogDescription>{tImmigration("rejectConfirmBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <label htmlFor={`reject-${request.id}`} className="text-sm font-medium">
              {tImmigration("rejectReason")}
            </label>
            <Input
              id={`reject-${request.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={1000}
            />
            {reason.trim().length === 0 && (
              <p className="text-xs text-muted-foreground">
                {tImmigration("rejectReasonRequired")}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejecting(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button
              onClick={() => void reject()}
              disabled={busy || reason.trim().length === 0}
            >
              {busy ? tCommon("states.saving") : tImmigration("rejectRequest")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}
