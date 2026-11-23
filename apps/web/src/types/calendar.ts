/** University calendar types. Mirrors the API contract exactly. */

export interface CalendarVacationRange {
  id: string;
  start_date: string;
  end_date: string;
  title: string;
  reason: string;
  is_cancelled: boolean;
  cancelled_at: string | null;
  cancelled_by_id: string | null;
  cancel_reason: string | null;
  created_by_id: string;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string;
  /** Live dates still governed by the range. */
  dates: string[];
  /** Live dates corrected individually; cancellation leaves them alone. */
  detached_dates: string[];
  /** Dates a shortening or cancellation voided. History, not live calendar. */
  voided_date_count: number;
}

export interface VacationRangeListResponse {
  items: CalendarVacationRange[];
  total: number;
}

export interface CalendarCoverage {
  start_date: string;
  end_date: string;
  weekday_defaults: Record<string, string>;
  total_days: number;
  default_working_days: number;
  default_non_working_days: number;
  working_days: number;
  non_working_days: number;
  holidays: string[];
  closures: string[];
  exceptional_working_days: string[];
  vacations: string[];
  exceptions: unknown[];
  voided_exception_count: number;
  days: unknown[];
}

export interface VacationRangeInput {
  start_date: string;
  end_date: string;
  title: string;
  reason: string;
}

export interface VacationRangeAdjustInput {
  start_date?: string;
  end_date?: string;
  change_reason: string;
}
