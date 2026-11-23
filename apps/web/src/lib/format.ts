/**
 * Presentation-only formatting helpers.
 *
 * Kept free of React so they can be used from server or client components and
 * unit-tested directly. Anything date-related takes the caller's locale so the
 * displayed value matches the language the user selected.
 */

const SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** Human-readable file size, e.g. `1.4 MB`. */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;

  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < SIZE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  return `${value.toFixed(value >= 10 ? 0 : 1)} ${SIZE_UNITS[unitIndex]}`;
}

/** Locale-aware date, falling back to an em dash for missing values. */
export function formatDate(
  value: string | null | undefined,
  locale: string,
): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleDateString(locale);
}

/** Locale-aware date and time. */
export function formatDateTime(
  value: string | null | undefined,
  locale: string,
): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(locale);
}
