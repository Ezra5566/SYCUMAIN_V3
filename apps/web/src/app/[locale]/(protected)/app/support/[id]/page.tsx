"use client";

import { useCallback, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Lock, Send, UserCheck } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { supportApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { normalizeApiError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { FilterSelect } from "@/components/ui/filter-select";
import { DetailList } from "@/components/ui/detail-list";
import { LoadingState } from "@/components/ui/loading-state";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import type { SupportTicket, SupportTicketStatus } from "@/types/platform";

const STATUS_VALUES: SupportTicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "WAITING_FOR_STUDENT",
  "RESOLVED",
  "CLOSED",
];

export default function SupportTicketPage() {
  const t = useTranslations("support");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { hasPermission, hasRole, user } = useAuth();
  const localizeError = useErrorMessage();

  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [working, setWorking] = useState(false);

  const fetchTicket = useCallback(() => supportApi.get(id), [id]);
  const { data, loading, error, refetch } = useApi<SupportTicket>(
    fetchTicket,
    [id],
    "support ticket",
  );

  const isStaff = hasRole("ADMIN") || hasRole("MANAGEMENT") || hasRole("TEACHER");
  const canRespond = hasPermission("support.respond");
  const canAssign = hasPermission("support.assign");
  const canResolve = hasPermission("support.resolve");

  const localized = localizeError(error);

  const run = async (
    action: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setWorking(true);
    try {
      await action();
      toast.success(successMessage);
      refetch();
    } catch (err) {
      toast.error(
        localizeError(normalizeApiError(err, "support action")).message,
      );
    } finally {
      setWorking(false);
    }
  };

  const sendReply = async () => {
    const text = reply.trim();
    if (!text) return;
    const asInternal = internal;
    await run(async () => {
      await supportApi.addMessage(id, text, asInternal);
      // The draft is cleared after the request settles, so anything typed while
      // it was in flight would be thrown away. Clear only what was actually
      // sent, and leave a newer draft (and its internal-note flag) untouched.
      setReply((current) => (current.trim() === text ? "" : current));
      setInternal((current) => (current === asInternal ? false : current));
    }, asInternal ? t("internalNoteAdded") : t("messageSent"));
  };

  const closed = data ? data.status === "CLOSED" || data.status === "RESOLVED" : false;

  return (
    <AppShell>
      <PageHeader
        title={data?.subject ?? t("title")}
        description={data ? t("ticketNumber", { number: data.ticket_number }) : undefined}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title"), href: "/app/support" },
          { label: data?.ticket_number ?? t("title") },
        ]}
        actions={
          data && isStaff ? (
            <>
              {canAssign && data.assignee_name !== user?.full_name && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={working}
                  onClick={() =>
                    run(
                      () =>
                        supportApi.update(data.id, {
                          assigned_to: user?.id ?? null,
                        }),
                      t("assignSucceeded"),
                    )
                  }
                >
                  <UserCheck className="me-1.5 h-4 w-4" aria-hidden="true" />
                  {t("assignToMe")}
                </Button>
              )}
              {canResolve && (
                <Button
                  variant={closed ? "outline" : "default"}
                  size="sm"
                  disabled={working}
                  onClick={() =>
                    run(
                      () =>
                        supportApi.update(data.id, {
                          status: closed ? "OPEN" : "CLOSED",
                        }),
                      closed ? t("reopenSucceeded") : t("closeSucceeded"),
                    )
                  }
                >
                  {closed ? t("reopenTicket") : t("closeTicket")}
                </Button>
              )}
            </>
          ) : undefined
        }
      />

      {loading ? (
        <LoadingState />
      ) : error ? (
        error.kind === "forbidden" ? (
          <EmptyState title={t("noPermission")} />
        ) : (
          <ErrorState
            title={localized.message}
            hint={localized.hint}
            onRetry={refetch}
          />
        )
      ) : !data ? (
        <EmptyState title={t("empty")} message={t("emptyHint")} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-6">
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-center gap-2 space-y-0">
                <CardTitle className="me-auto text-base">{t("messages")}</CardTitle>
                <StatusBadge tone={toneForStatus(data.status)}>
                  {t(`status.${data.status}`)}
                </StatusBadge>
                <StatusBadge tone={toneForStatus(data.priority)}>
                  {t(`priorities.${data.priority}`)}
                </StatusBadge>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="rounded-md border bg-muted/40 p-3">
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {t("description")}
                  </p>
                  <p className="whitespace-pre-wrap text-sm">
                    {data.description}
                  </p>
                </div>

                {(data.messages ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t("noMessages")}
                  </p>
                ) : (
                  <ul className="space-y-3">
                    {(data.messages ?? []).map((message) => (
                      <li
                        key={message.id}
                        className={
                          message.is_internal
                            ? "rounded-md border border-warning/30 bg-warning-soft p-3"
                            : "rounded-md border p-3"
                        }
                      >
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="font-medium text-foreground">
                            {message.author_name ?? tCommon("states.unknown")}
                          </span>
                          <span>
                            {new Date(message.created_at).toLocaleString(locale)}
                          </span>
                          {message.is_internal && (
                            <Badge variant="outline" className="gap-1 text-[10px]">
                              <Lock className="h-3 w-3" aria-hidden="true" />
                              {t("internalNote")}
                            </Badge>
                          )}
                        </div>
                        <p className="whitespace-pre-wrap text-sm">
                          {message.body}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}

                {(isStaff ? canRespond : true) && !closed && (
                  <div className="space-y-3 border-t pt-4">
                    <label htmlFor="support-reply" className="text-sm font-medium">
                      {t("addMessage")}
                    </label>
                    <Textarea
                      id="support-reply"
                      value={reply}
                      onChange={(event) => setReply(event.target.value)}
                      placeholder={t("messagePlaceholder")}
                      rows={4}
                      maxLength={5000}
                    />
                    {isStaff && (
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={internal}
                          onChange={(event) => setInternal(event.target.checked)}
                          className="mt-0.5 h-4 w-4 rounded border-input"
                        />
                        <span>
                          <span className="font-medium">{t("internalNote")}</span>
                          <span className="block text-xs text-muted-foreground">
                            {t("internalNoteHint")}
                          </span>
                        </span>
                      </label>
                    )}
                    <Button
                      size="sm"
                      disabled={working || !reply.trim()}
                      onClick={sendReply}
                    >
                      <Send className="me-1.5 h-4 w-4 rtl:rotate-180" aria-hidden="true" />
                      {t("sendMessage")}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{tCommon("labels.details")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <DetailList
                  columns={1}
                  items={[
                    {
                      label: tCommon("labels.name"),
                      value: data.student_name ?? tCommon("states.notSet"),
                    },
                    {
                      label: tCommon("labels.category"),
                      value: t(`categories.${data.category}`),
                    },
                    {
                      label: t("assignee"),
                      value: data.assignee_name ?? t("unassigned"),
                    },
                    {
                      label: t("createdAt"),
                      value: new Date(data.created_at).toLocaleString(locale),
                    },
                    {
                      label: t("updatedAt"),
                      value: new Date(data.updated_at).toLocaleString(locale),
                    },
                  ]}
                />

                {isStaff && canAssign && (
                  <FilterSelect
                    label={tCommon("labels.status")}
                    value={data.status}
                    showLabel
                    options={STATUS_VALUES.map((value) => ({
                      value,
                      label: t(`status.${value}`),
                    }))}
                    onChange={(value) =>
                      run(
                        () =>
                          supportApi.update(data.id, {
                            status: value as SupportTicketStatus,
                          }),
                        t("statusChanged"),
                      )
                    }
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </AppShell>
  );
}
