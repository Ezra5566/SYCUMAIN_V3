"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { studentApi } from "@/lib/student-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { PageHeader } from "@/components/ui/page-header";
import type { StudentDetail } from "@/types/student";

/**
 * Resolves "my profile" to the canonical student profile route.
 *
 * A student is never shown the staff directory, so they need an entry point to
 * their own record that does not require knowing its identifier. The backend
 * resolves the record from the session (`/students/me`); this page simply
 * forwards to `/app/students/{id}`, so there is only one profile
 * implementation to maintain.
 */
export default function MyProfilePage() {
  const t = useTranslations("studentProfile");
  const tCommon = useTranslations("common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const localizeError = useErrorMessage();

  const { data, loading, error, refetch } = useApi<StudentDetail>(
    () => studentApi.getMyStudent(),
    [],
    "own student record",
  );

  useEffect(() => {
    if (!data?.id) return;
    // Preserve an explicitly requested tab, so navigation can deep-link a
    // student straight to their own timetable instead of the overview.
    const tab = searchParams.get("tab");
    router.replace(
      tab ? `/app/students/${data.id}?tab=${encodeURIComponent(tab)}` : `/app/students/${data.id}`,
    );
  }, [data?.id, router, searchParams]);

  const noRecord = error?.status === 404;
  const localized = localizeError(error);

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />
      {loading ? (
        <LoadingState />
      ) : noRecord ? (
        <EmptyState title={t("noRecordTitle")} message={t("noRecordHint")} />
      ) : error ? (
        <ErrorState
          title={localized.message}
          hint={localized.hint}
          onRetry={refetch}
        />
      ) : (
        <LoadingState />
      )}
    </AppShell>
  );
}
