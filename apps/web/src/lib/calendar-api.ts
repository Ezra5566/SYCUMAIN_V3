/**
 * University calendar API client.
 *
 * The client never decides which dates a vacation covers: it sends the
 * institution's start and end date, and the server materialises, validates and
 * audits the range.
 */

import { apiFetch } from "@/lib/api";
import type {
  CalendarCoverage,
  CalendarVacationRange,
  VacationRangeAdjustInput,
  VacationRangeInput,
  VacationRangeListResponse,
} from "@/types/calendar";

const BASE = "/api/v1/academics/calendar";

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

class CalendarApiClient {
  async coverage(startDate: string, endDate: string): Promise<CalendarCoverage> {
    return apiFetch<CalendarCoverage>(
      `${BASE}/coverage${query({ start_date: startDate, end_date: endDate })}`,
    );
  }

  async listRanges(params: {
    startDate: string;
    endDate: string;
    includeCancelled?: boolean;
  }): Promise<VacationRangeListResponse> {
    return apiFetch<VacationRangeListResponse>(
      `${BASE}/vacation-ranges${query({
        start_date: params.startDate,
        end_date: params.endDate,
        include_cancelled: params.includeCancelled ? "true" : undefined,
      })}`,
    );
  }

  async createRange(input: VacationRangeInput): Promise<CalendarVacationRange> {
    return apiFetch<CalendarVacationRange>(`${BASE}/vacation-ranges`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  async adjustRange(
    rangeId: string,
    input: VacationRangeAdjustInput,
  ): Promise<CalendarVacationRange> {
    return apiFetch<CalendarVacationRange>(`${BASE}/vacation-ranges/${rangeId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  }

  async cancelRange(
    rangeId: string,
    reason: string,
  ): Promise<CalendarVacationRange> {
    return apiFetch<CalendarVacationRange>(
      `${BASE}/vacation-ranges/${rangeId}/cancellation`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
  }
}

export const calendarApi = new CalendarApiClient();
