import type { AcademicPeriod, TimetableEntry } from "@/types/academic";

/**
 * Student timetable presentation helpers.
 *
 * Timetable entries are weekly recurring sessions (`day_of_week` is 0 = Monday
 * through 6 = Sunday). A calendar date is therefore a class day only when the
 * weekday has an entry and the date falls inside the academic period returned
 * by the API. No semester dates or academic events are inferred here.
 */

export const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

const SHANGHAI_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: SHANGHAI_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export interface ShanghaiNow {
  dateIso: string;
  minutes: number;
  weekday: number;
}

export interface MonthCell {
  dateIso: string;
  day: number;
  inMonth: boolean;
  isToday: boolean;
  hasClass: boolean;
}

export interface ClassOccurrence {
  entry: TimetableEntry;
  dateIso: string;
  startMinutes: number;
  endMinutes: number;
  startAt: string;
  isToday: boolean;
  isCurrent: boolean;
  minutesUntilStart: number;
  minutesUntilEnd: number;
}

export function isoDate(year: number, monthIndex: number, day: number): string {
  return `${year.toString().padStart(4, "0")}-${(monthIndex + 1)
    .toString()
    .padStart(2, "0")}-${day.toString().padStart(2, "0")}`;
}

function dateFromIso(value: string): Date {
  // Noon UTC avoids a local-midnight offset changing the weekday.
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day, 12));
}

export function weekdayOf(value: string): number {
  return (dateFromIso(value).getUTCDay() + 6) % 7;
}

export function shanghaiNow(now = new Date()): ShanghaiNow {
  const parts = SHANGHAI_FORMATTER.formatToParts(now);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const dateIso = `${values.year}-${values.month}-${values.day}`;
  return {
    dateIso,
    minutes: Number(values.hour) * 60 + Number(values.minute),
    weekday: weekdayOf(dateIso),
  };
}

export function addDays(value: string, days: number): string {
  const date = dateFromIso(value);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function addMonths(
  year: number,
  monthIndex: number,
  delta: number,
): { year: number; monthIndex: number } {
  const date = new Date(Date.UTC(year, monthIndex + delta, 1, 12));
  return { year: date.getUTCFullYear(), monthIndex: date.getUTCMonth() };
}

export function daysInMonth(year: number, monthIndex: number): number {
  return new Date(Date.UTC(year, monthIndex + 1, 0, 12)).getUTCDate();
}

export function isWithinPeriod(
  dateIso: string,
  period: AcademicPeriod | null,
): boolean {
  if (!period) return false;
  return dateIso >= period.start_date && dateIso <= period.end_date;
}

export function entriesForDate(
  entries: TimetableEntry[],
  dateIso: string,
  period: AcademicPeriod | null,
): TimetableEntry[] {
  if (!isWithinPeriod(dateIso, period)) return [];
  const weekday = weekdayOf(dateIso);
  return entries
    .filter((entry) => !entry.is_deleted && entry.day_of_week === weekday)
    .sort((a, b) => a.start_time.localeCompare(b.start_time));
}

export function hasClassesOn(
  entries: TimetableEntry[],
  dateIso: string,
  period: AcademicPeriod | null,
): boolean {
  return entriesForDate(entries, dateIso, period).length > 0;
}

export function calendarCells(
  entries: TimetableEntry[],
  period: AcademicPeriod | null,
  year: number,
  monthIndex: number,
  todayIso: string,
): MonthCell[] {
  const firstWeekday = weekdayOf(isoDate(year, monthIndex, 1));
  const dayCount = daysInMonth(year, monthIndex);
  const cells: MonthCell[] = [];

  for (let index = 0; index < 42; index += 1) {
    const dayOffset = index - firstWeekday + 1;
    const date = new Date(Date.UTC(year, monthIndex, dayOffset, 12));
    const dateIso = date.toISOString().slice(0, 10);
    cells.push({
      dateIso,
      day: date.getUTCDate(),
      inMonth: date.getUTCMonth() === monthIndex,
      isToday: dateIso === todayIso,
      hasClass: hasClassesOn(entries, dateIso, period),
    });
  }

  return cells;
}

export function monthLabel(
  locale: string,
  year: number,
  monthIndex: number,
): string {
  return new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, monthIndex, 1, 12)));
}

export function weekdayInitials(locale: string): string[] {
  const formatter = new Intl.DateTimeFormat(locale, {
    weekday: "narrow",
    timeZone: "UTC",
  });
  return Array.from({ length: 7 }, (_, index) =>
    formatter.format(new Date(Date.UTC(2024, 0, 1 + index, 12))),
  );
}

export function dateLabel(locale: string, dateIso: string): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(dateFromIso(dateIso));
}

export function shortDateLabel(locale: string, dateIso: string): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(dateFromIso(dateIso));
}

export function timeLabel(
  locale: string,
  dateIso: string,
  time: string,
): string {
  const [hours, minutes] = time.split(":").map(Number);
  const date = new Date(
    `${dateIso}T${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:00+08:00`,
  );
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: SHANGHAI_TIME_ZONE,
  }).format(date);
}

export function timeRangeLabel(
  locale: string,
  dateIso: string,
  startTime: string,
  endTime: string,
): string {
  return `${timeLabel(locale, dateIso, startTime)}–${timeLabel(
    locale,
    dateIso,
    endTime,
  )}`;
}

function minutesOf(time: string): number {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
}

function occurrenceFor(
  entry: TimetableEntry,
  dateIso: string,
  now: ShanghaiNow,
): ClassOccurrence {
  const startMinutes = minutesOf(entry.start_time);
  const endMinutes = minutesOf(entry.end_time);
  const isToday = dateIso === now.dateIso;
  const startAt = new Date(
    `${dateIso}T${entry.start_time.slice(0, 5)}:00+08:00`,
  ).toISOString();

  return {
    entry,
    dateIso,
    startMinutes,
    endMinutes,
    startAt,
    isToday,
    isCurrent:
      isToday && startMinutes <= now.minutes && endMinutes > now.minutes,
    minutesUntilStart: isToday
      ? startMinutes - now.minutes
      : Math.round((new Date(startAt).getTime() - Date.now()) / 60000),
    minutesUntilEnd: isToday
      ? endMinutes - now.minutes
      : Math.round((new Date(startAt).getTime() - Date.now()) / 60000) +
        (endMinutes - startMinutes),
  };
}

/** The current class, or the next one after now, within the known period. */
export function currentOrNextClass(
  entries: TimetableEntry[],
  period: AcademicPeriod | null,
  now: ShanghaiNow,
  horizonDays = 21,
): ClassOccurrence | null {
  const candidates: ClassOccurrence[] = [];
  for (let offset = 0; offset <= horizonDays; offset += 1) {
    const dateIso = addDays(now.dateIso, offset);
    for (const entry of entriesForDate(entries, dateIso, period)) {
      const occurrence = occurrenceFor(entry, dateIso, now);
      if (
        occurrence.isCurrent ||
        (offset === 0 && occurrence.startMinutes > now.minutes) ||
        offset > 0
      ) {
        candidates.push(occurrence);
      }
    }
  }

  return (
    candidates
      .filter((occurrence) => occurrence.isCurrent || occurrence.startAt > new Date().toISOString())
      .sort((a, b) => a.startAt.localeCompare(b.startAt))[0] ??
    candidates.sort((a, b) => a.startAt.localeCompare(b.startAt))[0] ??
    null
  );
}

/** Future classes after the current one, ordered by actual date and time. */
export function upcomingClasses(
  entries: TimetableEntry[],
  period: AcademicPeriod | null,
  now: ShanghaiNow,
  limit = 5,
  horizonDays = 35,
): ClassOccurrence[] {
  const candidates: ClassOccurrence[] = [];
  for (let offset = 0; offset <= horizonDays; offset += 1) {
    const dateIso = addDays(now.dateIso, offset);
    for (const entry of entriesForDate(entries, dateIso, period)) {
      const occurrence = occurrenceFor(entry, dateIso, now);
      if (occurrence.isCurrent) continue;
      if (offset === 0 && occurrence.startMinutes <= now.minutes) continue;
      candidates.push(occurrence);
    }
  }

  return candidates
    .sort((a, b) => a.startAt.localeCompare(b.startAt))
    .slice(0, limit);
}

export function todayClasses(
  entries: TimetableEntry[],
  period: AcademicPeriod | null,
  now: ShanghaiNow,
): ClassOccurrence[] {
  return entriesForDate(entries, now.dateIso, period).map((entry) =>
    occurrenceFor(entry, now.dateIso, now),
  );
}

export function durationLabel(
  minutes: number,
): { key: "inMinutes" | "inHours" | "inHoursMinutes"; values: Record<string, number> } {
  if (minutes < 60) {
    return { key: "inMinutes", values: { minutes: Math.max(1, minutes) } };
  }
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (remainder === 0) {
    return { key: "inHours", values: { hours } };
  }
  return { key: "inHoursMinutes", values: { hours, minutes: remainder } };
}
