import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Phase 6 immigration cohort switch.
 *
 * Synthetic student only. The admission is the original intake; the placement
 * is deliberately in a later intake. The overview must keep the original
 * cohort, show the placement as academic-only, filter by original intake, and
 * export the trust column. The student banner must read the same pointer.
 */

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/en\/app/, { timeout: 25_000 });
}

async function expectOk(response: APIResponse, expected: number) {
  const body = await response.text();
  expect(response.status(), body).toBe(expected);
  return body ? JSON.parse(body) : null;
}

async function post<T>(
  page: Page,
  path: string,
  data: unknown,
  expected = 201,
): Promise<T> {
  return (await expectOk(
    await page.request.post(`${API_BASE}${path}`, { data }),
    expected,
  )) as T;
}

test.describe("immigration original-intake cohort", () => {
  test("placement does not move the cohort, and the filter/export/banner agree", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now().toString().slice(-7);
    const studentNumber = `STU-COH-${stamp}`;
    const lastName = `Cohort${stamp}`;

    await login(page, USERS.admin);

    const onboarded = await post<{ student: { id: string } }>(
      page,
      "/api/v1/students/onboard",
      {
        student_id: studentNumber,
        first_name: "Cohort",
        last_name: lastName,
        email: `cohort-${stamp}@example.com`,
      },
    );
    const studentId = onboarded.student.id;

    const programmeResponse = await page.request.get(
      `${API_BASE}/api/v1/academics/programs`,
    );
    const programme = (
      (await programmeResponse.json()) as { items: { id: string }[] }
    ).items[0];

    const spring = await post<{ id: string; name: string }>(
      page,
      "/api/v1/academics/periods",
      {
        name: `E2E Spring cohort ${stamp}`,
        code: `CS${stamp}`,
        start_date: "2025-01-15",
        end_date: "2025-05-20",
        status: "ACTIVE",
      },
    );
    const autumn = await post<{ id: string; name: string }>(
      page,
      "/api/v1/academics/periods",
      {
        name: `E2E Autumn cohort ${stamp}`,
        code: `CA${stamp}`,
        start_date: "2026-09-01",
        end_date: "2026-12-20",
        status: "ACTIVE",
      },
    );
    const springOffering = await post<{ id: string }>(
      page,
      "/api/v1/academics/program-offerings",
      {
        academic_period_id: spring.id,
        source_id: `e2e-cohort-spring-${stamp}`,
        name: `Cohort spring offering ${stamp}`,
        program_id: programme.id,
      },
    );
    const autumnOffering = await post<{ id: string }>(
      page,
      "/api/v1/academics/program-offerings",
      {
        academic_period_id: autumn.id,
        source_id: `e2e-cohort-autumn-${stamp}`,
        name: `Cohort autumn offering ${stamp}`,
        program_id: programme.id,
      },
    );

    const admission = await post<{ id: string }>(
      page,
      `/api/v1/students/${studentId}/admissions`,
      {
        admission_intake_id: spring.id,
        program_offering_id: springOffering.id,
        initial_status: "ACTIVE",
      },
    );
    await post(
      page,
      `/api/v1/students/${studentId}/placements`,
      {
        admission_id: admission.id,
        program_offering_id: autumnOffering.id,
        reason: "Synthetic Phase 6 forward placement",
      },
    );

    await page.goto(app("/app/immigration"));
    const row = page.getByRole("row").filter({ hasText: lastName });
    await expect(row).toBeVisible({ timeout: 25_000 });
    await expect(row.getByText(spring.name)).toBeVisible();
    await expect(row.getByText(autumn.name)).toBeVisible();
    await expect(row.getByText("Academic only")).toBeVisible();
    await expect(row.getByText("Verified", { exact: true })).toBeVisible();

    await page
      .getByLabel("Filter by original intake")
      .selectOption(spring.id);
    await expect(row).toBeVisible({ timeout: 25_000 });
    await page
      .getByLabel("Filter by original intake")
      .selectOption(autumn.id);
    await expect(row).toHaveCount(0, { timeout: 25_000 });

    const exported = await page.request.get(
      `${API_BASE}/api/v1/immigration/overview/export?intake_id=${spring.id}`,
    );
    expect(exported.status()).toBe(200);
    const csv = await exported.text();
    expect(csv).toContain(studentNumber);
    expect(csv).toContain(spring.name);
    expect(csv).toContain("VERIFIED");

    await page.goto(app(`/app/students/${studentId}`));
    await page.getByRole("tab", { name: "Immigration" }).click();
    const banner = page.getByRole("tabpanel", { name: "Immigration" });
    await expect(banner.getByText("Immigration cohort")).toBeVisible({
      timeout: 25_000,
    });
    await expect(banner.getByText(spring.name)).toBeVisible();
    await expect(banner.getByText(autumn.name)).toBeVisible();
  });
});
