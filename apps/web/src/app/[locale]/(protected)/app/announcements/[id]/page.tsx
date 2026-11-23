"use client";

import { useCallback, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { Archive, Send } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { announcementApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { normalizeApiError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { LoadingState } from "@/components/ui/loading-state";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { DetailList } from "@/components/ui/detail-list";
import { toast } from "@/components/ui/toast";
import { localeLabels, type Locale } from "@/i18n/routing";
import type { Announcement } from "@/types/platform";

export default function AnnouncementDetailPage() {
  const t = useTranslations("announcements");
  const tCommon = useTranslations("common");
  const locale = useLocale() as Locale;
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();
  const [working, setWorking] = useState(false);

  const fetchAnnouncement = useCallback(
    () => announcementApi.get(id, locale),
    [id, locale],
  );

  const { data, loading, error, refetch } = useApi<Announcement>(
    fetchAnnouncement,
    [id, locale],
    "announcement",
  );

  const canPublish = hasPermission("announcement.publish");
  const localized = localizeError(error);

  const run = async (action: () => Promise<unknown>, message: string) => {
    setWorking(true);
    try {
      await action();
      toast.success(message);
      refetch();
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "announcement action")).message);
    } finally {
      setWorking(false);
    }
  };

  const body = data?.resolved_body ?? data?.translations?.[0]?.body;

  return (
    <AppShell>
      <PageHeader
        title={data?.title ?? t("detailTitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title"), href: "/app/announcements" },
          { label: data?.title ?? t("detailTitle") },
        ]}
        actions={
          canPublish && data ? (
            <>
              {data.status === "DRAFT" && (
                <Button
                  size="sm"
                  disabled={working}
                  onClick={() =>
                    run(
                      () => announcementApi.publish(data.id),
                      t("publishSucceeded"),
                    )
                  }
                >
                  <Send className="me-1.5 h-4 w-4" aria-hidden="true" />
                  {tCommon("actions.publish")}
                </Button>
              )}
              {data.status !== "ARCHIVED" && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={working}
                  onClick={() =>
                    run(
                      () => announcementApi.archive(data.id),
                      t("unpublishSucceeded"),
                    )
                  }
                >
                  <Archive className="me-1.5 h-4 w-4" aria-hidden="true" />
                  {tCommon("actions.unpublish")}
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
        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row flex-wrap items-center gap-2 space-y-0">
              <CardTitle className="me-auto text-base">{data.title}</CardTitle>
              <StatusBadge tone={toneForStatus(data.priority)}>
                {t(`priorities.${data.priority}`)}
              </StatusBadge>
              <StatusBadge tone={toneForStatus(data.status)}>
                {t(`status.${data.status}`)}
              </StatusBadge>
            </CardHeader>
            <CardContent className="space-y-4">
              {data.resolved_locale && data.resolved_locale !== locale && (
                <p className="rounded-md border border-warning/30 bg-warning-soft p-3 text-sm text-warning">
                  {t("noTranslationForLocale")}
                </p>
              )}
              <div
                className="whitespace-pre-wrap text-sm leading-relaxed"
                dir={data.resolved_locale === "ar" ? "rtl" : undefined}
              >
                {body}
              </div>
              <DetailList
                columns={3}
                items={[
                  {
                    label: t("audience"),
                    value: (
                      <Badge variant="outline">
                        {t(`audiences.${data.audience_type}`)}
                      </Badge>
                    ),
                  },
                  {
                    label: t("publishedAt"),
                    value: data.published_at
                      ? new Date(data.published_at).toLocaleString(locale)
                      : tCommon("states.notSet"),
                  },
                  {
                    label: t("publishedBy"),
                    value: data.author_name ?? tCommon("states.notSet"),
                  },
                ]}
              />
            </CardContent>
          </Card>

          {(data.translations ?? []).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("translations")}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {(data.translations ?? []).map((translation) => (
                  <div key={translation.locale} className="rounded-md border p-3">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {localeLabels[translation.locale as Locale] ??
                        translation.locale}
                      {data.default_locale === translation.locale && (
                        <span className="ms-2 normal-case">
                          ({t("originalLanguage")})
                        </span>
                      )}
                    </p>
                    <p className="font-medium">{translation.title}</p>
                    <p
                      className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground"
                      dir={translation.locale === "ar" ? "rtl" : undefined}
                    >
                      {translation.body}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}
