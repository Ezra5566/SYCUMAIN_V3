import { cn } from "@/lib/utils";

/** Neutral shimmer block used for loading placeholders. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("scu-skeleton rounded-md", className)}
      {...props}
    />
  );
}

/** Convenience skeleton for a table with the given number of rows/columns. */
export function TableSkeleton({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2 p-4" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={colIndex}
              className={cn("h-6 flex-1", colIndex === 0 && "max-w-[220px]")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
