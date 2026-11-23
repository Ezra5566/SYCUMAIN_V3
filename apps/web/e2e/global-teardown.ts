import { request } from "@playwright/test";

import { ADMIN, API_BASE } from "./accounts";

/**
 * Browser-suite teardown: retire the records the suite created.
 *
 * Every lifecycle test onboards a real student through the real API, because
 * that is the workflow under test. Those records persist — institutional data is
 * archived, never hard-deleted — so without this step each run leaves more
 * "E2E Onboard…" students behind, and they eventually crowd the directory,
 * the reports and the active-student counts.
 *
 * The teardown marks every `STU-E2E-*` student INACTIVE. That is not just
 * cosmetic: an inactive student record cannot sign in (see the access gate in
 * the auth service), so the throwaway accounts also stop being usable
 * credentials. The rows themselves stay, exactly as an operator would expect
 * from an archive operation.
 *
 * Best-effort by design: if no stack is reachable the run's own results are
 * still the point, so this reports and returns rather than failing the suite.
 */

/** Students created by `newStudent()` in stage8b.spec.ts. */
const TEST_NUMBER_PREFIX = "STU-E2E-";

const PAGE_SIZE = 100;

interface StudentListResponse {
  items: { id: string; student_id: string }[];
  meta: { total: number; total_pages: number };
}

interface StudentHousingResponse {
  has_assignment: boolean;
  assignment: { id: string } | null;
}

export default async function globalTeardown(): Promise<void> {
  const context = await request.newContext({ baseURL: API_BASE });

  try {
    const login = await context.post("/api/v1/auth/login", { data: ADMIN });
    if (!login.ok()) {
      console.warn(
        `[teardown] could not sign in as admin (HTTP ${login.status()}); leaving test students in place.`,
      );
      return;
    }

    const ids: string[] = [];
    let page = 1;

    for (;;) {
      const response = await context.get("/api/v1/students", {
        params: {
          search: TEST_NUMBER_PREFIX,
          page_size: PAGE_SIZE,
          page,
        },
      });
      if (!response.ok()) {
        console.warn(
          `[teardown] student lookup failed (HTTP ${response.status()}); leaving test students in place.`,
        );
        return;
      }

      const body = (await response.json()) as StudentListResponse;
      ids.push(...body.items.map((item) => item.id));

      if (page >= body.meta.total_pages || body.items.length === 0) break;
      page += 1;
    }

    if (ids.length === 0) return;

    // Free the beds first. The housing test assigns a test student to a real
    // bed, and a dangling ACTIVE assignment would slowly fill the seeded
    // estate run after run — the next run's room would then be full.
    let ended = 0;
    for (const studentRecordId of ids) {
      const housing = await context.get(
        `/api/v1/housing/students/${studentRecordId}/housing`,
      );
      if (!housing.ok()) continue;
      const body = (await housing.json()) as StudentHousingResponse;
      if (!body.has_assignment || !body.assignment) continue;
      const end = await context.post(
        `/api/v1/housing/assignments/${body.assignment.id}/end`,
      );
      if (end.ok()) ended += 1;
    }

    const retire = await context.post("/api/v1/students/bulk/status", {
      data: { student_ids: ids, status: "INACTIVE" },
    });
    if (!retire.ok()) {
      console.warn(
        `[teardown] could not retire ${ids.length} test students (HTTP ${retire.status()}).`,
      );
      return;
    }

    const result = (await retire.json()) as { succeeded: number };
    console.log(
      `[teardown] retired ${result.succeeded}/${ids.length} browser-test students ` +
        `(status INACTIVE), ended ${ended} housing assignment(s).`,
    );
  } catch (error) {
    console.warn(`[teardown] skipped: ${(error as Error).message}`);
  } finally {
    await context.dispose();
  }
}
