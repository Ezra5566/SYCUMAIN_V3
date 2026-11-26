import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { TableSkeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface Column<T> {
  /** Stable identifier for the column. */
  key: string;
  header: React.ReactNode;
  cell: (row: T) => React.ReactNode;
  className?: string;
  /** Hide this column below the `sm` breakpoint. */
  hideOnMobile?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyMessage?: string;
  /** Render a mobile-friendly stacked list instead of a scrolling table. */
  mobileCard?: (row: T) => React.ReactNode;
  /** Accessible name for the table, read by screen readers. */
  label?: string;
  className?: string;
}

/**
 * Dense administration table with consistent loading / empty / error handling.
 *
 * On small screens, columns marked `hideOnMobile` are dropped and, when a
 * `mobileCard` renderer is supplied, rows become stacked cards rather than a
 * horizontally scrolling table.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  error = null,
  onRetry,
  emptyTitle,
  emptyMessage,
  mobileCard,
  label,
  className,
}: DataTableProps<T>) {
  const shell = cn(
    "overflow-hidden rounded-[22px] border border-border bg-card/70 shadow-card backdrop-blur-xl",
    className,
  );

  if (loading) {
    return (
      <div className={shell}>
        <TableSkeleton rows={6} columns={Math.min(columns.length, 5)} />
      </div>
    );
  }

  if (error) {
    return (
      <div className={shell}>
        <ErrorState message={error} onRetry={onRetry} />
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className={shell}>
        <EmptyState title={emptyTitle} message={emptyMessage} />
      </div>
    );
  }

  return (
    <div className={shell}>
      {/* Mobile: stacked cards */}
      {mobileCard && (
        <div className="motion-list divide-y divide-border/70 sm:hidden">
          {rows.map((row) => (
            <div key={rowKey(row)} className="p-4">
              {mobileCard(row)}
            </div>
          ))}
        </div>
      )}

      {/* Desktop / tablet: dense table */}
      <div className={cn(mobileCard && "hidden sm:block")}>
        <Table className="motion-table" aria-label={label}>
          <TableHeader>
            <TableRow className="border-border/80 bg-muted/45 hover:bg-muted/45">
              {columns.map((column) => (
                <TableHead
                  key={column.key}
                  className={cn(
                    "h-9 whitespace-nowrap px-3 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground",
                    column.hideOnMobile && "hidden md:table-cell",
                    column.className,
                  )}
                >
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={rowKey(row)} className="border-border/60">
                {columns.map((column) => (
                  <TableCell
                    key={column.key}
                    className={cn(
                      "px-3 py-2.5",
                      column.hideOnMobile && "hidden md:table-cell",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
