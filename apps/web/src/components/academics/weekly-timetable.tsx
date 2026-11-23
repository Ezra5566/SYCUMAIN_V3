"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { CalendarDays, Clock3, DoorOpen, UserRound } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TimetableEntry } from "@/types/academic";

const DAY_KEYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

const DAY_SHORT_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

// Restrained institutional tones. Chosen by course code so the same subject
// keeps its colour across cells and weeks.
const CARD_TONES = [
  "border-s-primary/70 bg-primary/[0.055]",
  "border-s-gold/80 bg-gold/[0.09]",
  "border-s-success/70 bg-success-soft/70",
  "border-s-info/70 bg-info-soft/70",
  "border-s-warning/80 bg-warning-soft/70",
  "border-s-destructive/60 bg-destructive/[0.055]",
] as const;

function toneFor(entry: TimetableEntry): string {
  const key = entry.course_code ?? entry.course_name ?? entry.id;
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) % 997;
  }
  return CARD_TONES[hash % CARD_TONES.length];
}

function timeOf(value: string): string {
  return value.slice(0, 5);
}

function SessionCard({
  entry,
  compact = false,
}: {
  entry: TimetableEntry;
  compact?: boolean;
}) {
  const t = useTranslations("academics");
  const tCommon = useTranslations("common");
  const title = entry.course_name ?? entry.course_code ?? tCommon("states.notSet");
  const section = [entry.course_code, entry.section_code ?? entry.source_label]
    .filter(Boolean)
    .join(" · ");

  return (
    <article
      className={cn(
        "rounded-md border border-border/60 border-s-[3px] p-2 text-start shadow-sm",
        toneFor(entry),
        compact ? "space-y-1" : "space-y-1",
      )}
    >
      {section && (
        <p className="truncate font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          {section}
        </p>
      )}
      <p className="text-[12px] font-semibold leading-snug">{title}</p>
      <p className="flex items-center gap-1 text-[11px] tabular-nums text-foreground/80" dir="ltr">
        <Clock3 className="h-3 w-3 shrink-0" aria-hidden="true" />
        {timeOf(entry.start_time)}–{timeOf(entry.end_time)}
        {entry.slot_label && (
          <span className="text-muted-foreground">· {entry.slot_label}</span>
        )}
      </p>
      {entry.classroom_name && (
        <p className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">
          <DoorOpen className="h-3 w-3 shrink-0" aria-hidden="true" />
          {entry.classroom_name}
        </p>
      )}
      {entry.teacher_names.length > 0 && (
        <p className="flex items-center gap-1 truncate text-[11px] text-muted-foreground">
          <UserRound className="h-3 w-3 shrink-0" aria-hidden="true" />
          {entry.teacher_names.join(", ")}
        </p>
      )}
    </article>
  );
}

/**
 * Conventional weekly timetable.
 *
 * Rows are the distinct official start times in the data, not invented bell
 * periods. A session keeps its real start and end times in the card, so a
 * session spanning several periods is shown as one visual block (for example
 * 08:20–12:00, periods 1–4). The mobile presentation switches to a day
 * selector instead of squeezing seven columns onto a phone.
 */
export function WeeklyTimetable({ entries }: { entries: TimetableEntry[] }) {
  const t = useTranslations("academics");
  const todayIndex = useMemo(() => {
    const jsDay = new Date().getDay();
    return jsDay === 0 ? 6 : jsDay - 1;
  }, []);

  const sorted = useMemo(
    () =>
      [...entries].sort((a, b) =>
        a.day_of_week === b.day_of_week
          ? a.start_time.localeCompare(b.start_time) || a.end_time.localeCompare(b.end_time)
          : a.day_of_week - b.day_of_week,
      ),
    [entries],
  );

  const days = useMemo(() => {
    const present = new Set(sorted.map((entry) => entry.day_of_week));
    const weekday = [0, 1, 2, 3, 4];
    return [...weekday, 5, 6].filter(
      (day) => weekday.includes(day) || present.has(day),
    );
  }, [sorted]);

  const startTimes = useMemo(
    () => [...new Set(sorted.map((entry) => entry.start_time))].sort(),
    [sorted],
  );

  const byCell = useMemo(() => {
    const map = new Map<string, TimetableEntry[]>();
    for (const entry of sorted) {
      const key = `${entry.day_of_week}-${entry.start_time}`;
      map.set(key, [...(map.get(key) ?? []), entry]);
    }
    return map;
  }, [sorted]);

  const firstDayWithSessions = days.find((day) =>
    sorted.some((entry) => entry.day_of_week === day),
  );
  const [selectedDay, setSelectedDay] = useState<number>(() =>
    days.includes(todayIndex) ? todayIndex : (firstDayWithSessions ?? days[0] ?? 0),
  );
  const activeDay = days.includes(selectedDay) ? selectedDay : (days[0] ?? 0);
  const dayEntries = sorted.filter((entry) => entry.day_of_week === activeDay);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">{t("weeklyHint")}</p>
        <p className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
          {t("scheduledSessions", { count: entries.length })}
        </p>
      </div>

      {/* Desktop and tablet: days as columns, start times as rows. */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[720px] table-fixed border-separate border-spacing-0 text-sm">
          <caption className="sr-only">{t("weeklyHint")}</caption>
          <colgroup>
            <col className="w-[78px]" />
            {days.map((day) => (
              <col key={day} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th
                scope="col"
                className="sticky top-0 z-10 border-b bg-card p-2 text-start text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
              >
                {t("time")}
              </th>
              {days.map((day) => (
                <th
                  key={day}
                  scope="col"
                  className={cn(
                    "sticky top-0 z-10 border-b p-2 text-start text-[11px] font-semibold",
                    day === todayIndex ? "bg-primary/[0.06] text-primary" : "bg-card",
                  )}
                >
                  {t(`days.${DAY_KEYS[day]}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {startTimes.map((start) => (
              <tr key={start}>
                <th
                  scope="row"
                  className="border-b bg-muted/25 p-2 align-top text-[11px] font-medium tabular-nums text-muted-foreground"
                  dir="ltr"
                >
                  {timeOf(start)}
                </th>
                {days.map((day) => {
                  const cell = byCell.get(`${day}-${start}`) ?? [];
                  return (
                    <td
                      key={day}
                      className={cn(
                        "border-b border-s border-border/50 p-1.5 align-top",
                        day === todayIndex && "bg-primary/[0.025]",
                      )}
                    >
                      {cell.length > 0 && (
                        <div className="space-y-1.5">
                          {cell.map((entry) => (
                            <SessionCard key={entry.id} entry={entry} compact />
                          ))}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: a day selector and an agenda, rather than seven squeezed columns. */}
      <div className="space-y-3 md:hidden">
        <div
          role="tablist"
          aria-label={t("weekDays")}
          className="flex gap-1 overflow-x-auto pb-1"
        >
          {days.map((day) => (
            <button
              key={day}
              type="button"
              role="tab"
              aria-selected={day === activeDay}
              onClick={() => setSelectedDay(day)}
              className={cn(
                "min-w-14 rounded-lg border px-2 py-2 text-center text-[11px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                day === activeDay
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-muted-foreground hover:bg-muted",
              )}
            >
              <span className="block">{t(`daysShort.${DAY_SHORT_KEYS[day]}`)}</span>
              <span className="block text-[10px] font-normal opacity-80">
                {sorted.filter((entry) => entry.day_of_week === day).length}
              </span>
            </button>
          ))}
        </div>

        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            {t(`days.${DAY_KEYS[activeDay]}`)}
          </p>
          {dayEntries.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border/80 bg-muted/15 px-4 py-6 text-center text-xs text-muted-foreground">
              {t("noSessionsOnDay")}
            </p>
          ) : (
            <ol className="space-y-2">
              {dayEntries.map((entry) => (
                <li key={entry.id}>
                  <SessionCard entry={entry} />
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}