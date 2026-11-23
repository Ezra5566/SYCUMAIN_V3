import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * App-level loading shell.
 *
 * Keeping the navigation visible during a slow route transition avoids a
 * blank page without pretending that record data is already available.
 */
export default function AppLoading() {
  return (
    <AppShell>
      <div className="space-y-4" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading page</span>
        <Skeleton className="h-32 w-full rounded-2xl" />
        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    </AppShell>
  );
}
