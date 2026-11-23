import { cn } from "@/lib/utils";

export interface DetailItem {
  label: string;
  value: React.ReactNode;
  /** Span both columns — useful for long values like addresses. */
  wide?: boolean;
}

interface DetailListProps {
  items: DetailItem[];
  columns?: 1 | 2 | 3;
  className?: string;
}

const COLUMN_CLASSES: Record<1 | 2 | 3, string> = {
  1: "grid-cols-1",
  2: "grid-cols-1 sm:grid-cols-2",
  3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
};

/**
 * Standard read-only label/value grid used across profile and detail views.
 * Renders "—" for empty values so blank fields are explicit rather than invisible.
 */
export function DetailList({ items, columns = 2, className }: DetailListProps) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-4", COLUMN_CLASSES[columns], className)}>
      {items.map((item, index) => (
        <div
          key={`${item.label}-${index}`}
          className={cn("min-w-0", item.wide && "sm:col-span-2")}
        >
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {item.label}
          </dt>
          <dd className="mt-1 break-words text-sm">{item.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
