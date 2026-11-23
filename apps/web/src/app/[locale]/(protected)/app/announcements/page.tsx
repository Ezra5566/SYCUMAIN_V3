"use client";

import { useCallback, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Megaphone, Pin } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { announcementApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadingState } from "@/components/ui/loading-state";
import { ErrorState } from "@/components/ui/error-state";
import { ComposeAnnouncementDialog } from "@/components/announcements/compose-dialog";
import type { AnnouncementListResponse, AnnouncementStatus } from "@/types/platform";

const STATUS_VALUES: AnnouncementStatus[] = [
  "DRAFT",
  "SCHEDULED",
  "PUBLISHED",
  "ARCHIVED",
];

const PAGE_SIZE = 20;

export default function AnnouncementsPage() {
  const t = useTranslations("announcements");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<AnnouncementStatus | "">("");
  const [page, setPage] = useState(1);
  const [composing, setComposing] = useState(false);

  const canManage = hasPermission("announcement.edit");
  const canCreate = hasPermission("announcement.create");

  const fetchFeed = useCallback(
    () =>
      announcementApi.list({
        locale,
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: (statusFilter as AnnouncementStatus) || undefined,
      }),
    [locale, page, search, statusFilter],
  );

  const { data, loading, error, refetch } = useApi<AnnouncementListResponse>(
    fetchFeed,
    [locale, page, search, statusFilter],
    "announcements",
  );

  const statusOptions = useMemo(
    () => [
      { value: "", label: `${tCommon("labels.status")} — ${tCommon("labels.all")}` },
      ...STATUS_VALUES.map((value) => ({ value, label: t(`status.${value}`) })),
    ],
    [t, tCommon],
  );

  const forbidden = error?.kind === "forbidden";
  const localized = localizeError(error);
  const items = data?.items ?? [];
  const totalPages =
    data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;

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
          canCreate ? (
            <Button size="sm" onClick={() => setComposing(true)}>
              <Megaphone className="me-1.5 h-4 w-4" aria-hidden="true" />
              {t("create")}
            </Button>
          ) : undefined
        }
      />

      {forbidden ? (
        <EmptyState title={t("noPermission")} />
      ) : (
        <>
          {(search || statusFilter || canManage) && (
            <Card className="mb-4">
              <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
                <SearchInput
                  value={search}
                  onChange={(value) => {
                    setSearch(value);
                    setPage(1);
                  }}
                  placeholder={tCommon("labels.searchPlaceholder")}
                  className="sm:max-w-sm sm:flex-1"
                />
                {canManage && (
                  <FilterSelect
                    label={tCommon("labels.status")}
                    value={statusFilter}
                    options={statusOptions}
                    showLabel
                    onChange={(value) => {
                      setStatusFilter(value as AnnouncementStatus | "");
                      setPage(1);
                    }}
                    className="sm:w-64"
                  />
                )}
              </CardContent>
            </Card>
          )}

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
            <ul className="space-y-3">
              {items.map((item) => (
                <li key={item.id}>
                  <Card>
                    <CardContent className="space-y-2 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            {item.is_pinned && (
                              <Pin
                                className="h-3.5 w-3.5 text-muted-foreground"
                                aria-label={t("fieldTitle")}
                              />
                            )}
                            <Link
                              href={`/app/announcements/${item.id}`}
                              className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {item.title}
                            </Link>
                          </div>
                          {item.summary && (
                            <p className="line-clamp-2 text-sm text-muted-foreground">
                              {item.summary}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          <StatusBadge tone={toneForStatus(item.priority)}>
                            {t(`priorities.${item.priority}`)}
                          </StatusBadge>
                          <StatusBadge tone={toneForStatus(item.status)}>
                            {t(`status.${item.status}`)}
                          </StatusBadge>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <Badge variant="outline" className="text-[10px]">
                          {t(`audiences.${item.audience_type}`)}
                        </Badge>
                        {item.published_at && (
                          <span>
                            {t("publishedAt")}:{" "}
                            {new Date(item.published_at).toLocaleDateString(locale)}
                          </span>
                        )}
                        {item.author_name && (
                          <span>
                            {t("publishedBy")}: {item.author_name}
                          </span>
                        )}
                        {item.resolved_locale !== locale && (
                          <span className="text-warning">
                            {t("noTranslationForLocale")}
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                </li>
              ))}
            </ul>
          )}

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

      {canCreate && (
        <ComposeAnnouncementDialog
          open={composing}
          onOpenChange={setComposing}
          onCreated={() => {
            setComposing(false);
            refetch();
          }}
        />
      )}
    </AppShell>
  );
}
