"use client";

import { useCallback, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Check, CheckCheck } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { notificationApi } from "@/lib/platform-api";
import { NOTIFICATIONS_CHANGED } from "@/components/layout/notification-bell";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { LoadingState } from "@/components/ui/loading-state";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { NotificationListResponse } from "@/types/platform";

const PAGE_SIZE = 20;

export default function NotificationsPage() {
  const t = useTranslations("notifications");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const localizeError = useErrorMessage();
  const [page, setPage] = useState(1);
  const [working, setWorking] = useState(false);

  const fetchNotifications = useCallback(
    () => notificationApi.list({ page, page_size: PAGE_SIZE }),
    [page],
  );

  const { data, loading, error, refetch } = useApi<NotificationListResponse>(
    fetchNotifications,
    [page],
    "notifications",
  );

  const localized = localizeError(error);
  const items = data?.items ?? [];
  const totalPages =
    data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;

  /**
   * Compose the localized second line for a notification.
   *
   * The API stores a machine-readable type plus parameters (never English
   * prose), so the sentence is built here and can differ per language. A type
   * with no message mapping falls back to its own translated label.
   *
   * The sentence deliberately does not interpolate `params`: those values are
   * internal identifiers (bed and announcement UUIDs), not text a reader should
   * ever see. Navigation is what the `link_url` is for.
   */
  const describe = (type: string) => {
    const messageKey = TYPE_MESSAGE_KEY[type];
    if (!messageKey) return null;
    return t(`messages.${messageKey}`);
  };

  /** Keep the header badge in step with this page's list. */
  const announceReadChange = () =>
    window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));

  const markAllRead = async () => {
    setWorking(true);
    try {
      await notificationApi.markAllRead();
      toast.success(t("allMarkedRead"));
      announceReadChange();
      refetch();
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "mark all read")).message);
    } finally {
      setWorking(false);
    }
  };

  const markRead = async (id: string) => {
    try {
      await notificationApi.markRead(id);
      announceReadChange();
      refetch();
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "mark read")).message);
    }
  };

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
          data && data.unread_count > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={markAllRead}
              disabled={working}
            >
              <CheckCheck className="me-1.5 h-4 w-4" aria-hidden="true" />
              {t("markAllRead")}
            </Button>
          ) : undefined
        }
      />

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState
          title={localized.message}
          hint={localized.hint}
          onRetry={refetch}
        />
      ) : items.length === 0 ? (
        <EmptyState title={t("empty")} message={t("emptyHint")} />
      ) : (
        <>
          <ul className="space-y-2">
            {items.map((item) => {
              const unread = !item.read_at;
              return (
                <li key={item.id}>
                  <Card className={cn(unread && "border-primary/40 bg-primary/5")}>
                    <CardContent className="flex flex-wrap items-start justify-between gap-3 p-4">
                      <div className="min-w-0 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          {unread && (
                            <span
                              className="h-2 w-2 shrink-0 rounded-full bg-primary"
                              aria-hidden="true"
                            />
                          )}
                          <p className="font-medium">{t(`types.${item.type}`)}</p>
                          {unread && (
                            <span className="sr-only">{t("unread")}</span>
                          )}
                        </div>
                        {describe(item.type) && (
                          <p className="text-sm text-muted-foreground">
                            {describe(item.type)}
                          </p>
                        )}
                        <p className="text-xs text-muted-foreground">
                          {new Date(item.created_at).toLocaleString(locale)}
                        </p>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {item.link_url && (
                          <Button asChild variant="outline" size="sm">
                            <Link href={item.link_url}>{t("viewRelated")}</Link>
                          </Button>
                        )}
                        {unread && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => markRead(item.id)}
                            aria-label={t("markRead")}
                          >
                            <Check className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </li>
              );
            })}
          </ul>

          {data && data.total > PAGE_SIZE && (
            <Pagination
              page={data.page}
              pageSize={data.page_size}
              total={data.total}
              totalPages={totalPages}
              onPageChange={setPage}
            />
          )}
        </>
      )}
    </AppShell>
  );
}

/**
 * Maps a notification type to the message key that carries its human-readable
 * text. Adding a backend notification type requires only a new entry here plus
 * the message — no changes to the rendering logic.
 *
 * Types absent from this map render only their label, which is the correct
 * degradation: a bare status chip is better than an invented sentence.
 */
const TYPE_MESSAGE_KEY: Record<string, string> = {
  IMMIGRATION_CHANGE_SUBMITTED: "immigrationSubmitted",
  IMMIGRATION_CHANGE_APPROVED: "immigrationApproved",
  IMMIGRATION_CHANGE_REJECTED: "immigrationRejected",
  IMMIGRATION_DOCUMENT_UPLOADED: "immigrationDocumentUploaded",
  HOUSING_ASSIGNMENT_CREATED: "housingAssigned",
  HOUSING_ASSIGNMENT_TRANSFERRED: "housingTransferred",
  HOUSING_ASSIGNMENT_ENDED: "housingEnded",
  SUPPORT_TICKET_CREATED: "supportCreated",
  SUPPORT_TICKET_REPLIED: "supportReplied",
  SUPPORT_TICKET_STATUS_CHANGED: "supportStatusChanged",
  SUPPORT_TICKET_ASSIGNED: "supportAssigned",
  ANNOUNCEMENT_PUBLISHED: "announcementPublished",
  DOCUMENT_UPLOADED: "documentUploaded",
};
