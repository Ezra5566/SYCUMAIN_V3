import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Phase 3 placement panel.
 *
 * Uses only synthetic data in the disposable E2E stack. The first test assigns
 * a later intake, then changes to an earlier intake with a reason, and proves
 * the original admission is untouched. The second renders the same panel in
 * Arabic to verify RTL and localized strings.
 */

async function login(page: Page, user: { email: string; password: string }, prefix = "/en") {
  await page.goto(`${prefix}/login`);
  await page.getByLabel(/email|البريد/i).fill(user.email);
  await page.getByLabel(/password|كلمة المرور/i).fill(user.password);
  await page.getByRole("button").filter({ hasText: /sign in|تسجيل الدخول/i }).click();
  await page.waitForURL(new RegExp(`${prefix}/app`), { timeout: 25_000 });
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

test.describe.serial("academic placement", () => {
  let studentId = "";
  let studentNumber = "";
  let admissionIntake = "";
  let earlierIntake = "";
  let laterIntake = "";

  test("assigns, changes to an earlier intake with authorization, and keeps admission history", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now().toString().slice(-7);
    studentNumber = `STU-PLACE-${stamp}`;
    await login(page, USERS.admin);

    const onboarded = await post<{ student: { id: string } }>(
      page,
      "/api/v1/students/onboard",
      {
        student_id: studentNumber,
        first_name: "Placement",
        last_name: `Candidate${stamp}`,
        email: `placement-${stamp}@example.com`,
      },
    );
    studentId = onboarded.student.id;

    const programs = await expectOk(
      await page.request.get(`${API_BASE}/api/v1/academics/programs`),
      200,
    );
    const programId = (programs as { items: { id: string }[] }).items[0].id;

    const intakes: Record<string, { id: string; name: string }> = {};
    const offerings: Record<string, string> = {};
    for (const [key, year] of [
      ["earlier", 2031],
      ["admission", 2032],
      ["later", 2033],
    ] as const) {
      const name = `E2E placement intake ${stamp}-${key}`;
      const intake = await post<{ id: string; name: string }>(
        page,
        "/api/v1/academics/periods",
        {
          name,
          code: `EP${stamp}${key.slice(0, 2).toUpperCase()}`,
          start_date: `${year}-09-01`,
          end_date: `${year}-12-20`,
          status: "ACTIVE",
        },
      );
      intakes[key] = intake;
      const offering = await post<{ id: string }>(
        page,
        "/api/v1/academics/program-offerings",
        {
          academic_period_id: intake.id,
          source_id: `e2e-placement-${stamp}-${key}`,
          name: `E2E placement offering ${stamp}-${key}`,
          program_id: programId,
        },
      );
      offerings[key] = offering.id;
    }
    admissionIntake = intakes.admission.name;
    earlierIntake = intakes.earlier.name;
    laterIntake = intakes.later.name;

    const admission = await post<{ id: string }>(
      page,
      `/api/v1/students/${studentId}/admissions`,
      {
        admission_intake_id: intakes.admission.id,
        program_offering_id: offerings.admission,
        initial_status: "ACTIVE",
      },
    );

    await page.goto(app(`/app/students/${studentId}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    const panel = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Academic placement", exact: true }),
    });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("No current placement")).toBeVisible();

    await panel.getByRole("button", { name: "Assign placement" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("Admission episode").selectOption(admission.id);
    await dialog.getByLabel("Placement intake").selectOption(intakes.later.id);
    await expect(
      dialog
        .getByLabel("Program offering")
        .locator(`option[value="${offerings.later}"]`),
    ).toHaveCount(1);
    await dialog.getByLabel("Program offering").selectOption(offerings.later);
    await dialog.getByRole("button", { name: "Save placement" }).click();
    await expect(page.getByText("Academic placement updated.")).toBeVisible();

    await expect(panel).toContainText(laterIntake);
    await expect(panel).toContainText(admissionIntake);

    await panel.getByRole("button", { name: "Change placement" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Admission episode").selectOption(admission.id);
    await dialog.getByLabel("Placement intake").selectOption(intakes.earlier.id);
    await expect(
      dialog
        .getByLabel("Program offering")
        .locator(`option[value="${offerings.earlier}"]`),
    ).toHaveCount(1);
    await dialog.getByLabel("Program offering").selectOption(offerings.earlier);
    await expect(dialog.getByText("Earlier-intake placement")).toBeVisible();
    await dialog
      .getByLabel("Authorization reason")
      .fill("E2E approved catch-up teaching placement");
    await dialog.getByRole("button", { name: "Save placement" }).click();
    await expect(page.getByText("Academic placement updated.")).toBeVisible();

    await expect(panel.getByText("Earlier-intake placement")).toBeVisible();
    await expect(panel.getByText("Admin User").first()).toBeVisible();
    await expect(
      panel.getByText("E2E approved catch-up teaching placement"),
    ).toBeVisible();
    await expect(panel).toContainText(admissionIntake);
    await expect(panel).toContainText(earlierIntake);
    await expect(panel.locator("ol > li")).toHaveCount(2);

    const history = (await expectOk(
      await page.request.get(
        `${API_BASE}/api/v1/students/${studentId}/placements`,
      ),
      200,
    )) as {
      items: {
        is_current: boolean;
        is_earlier_intake_placement: boolean;
        authorization_reason: string | null;
        admission_intake_name: string;
        placement_intake_name: string;
      }[];
    };
    expect(history.items).toHaveLength(2);
    const current = history.items.find((item) => item.is_current);
    expect(current?.is_earlier_intake_placement).toBe(true);
    expect(current?.authorization_reason).toBe(
      "E2E approved catch-up teaching placement",
    );
    expect(current?.admission_intake_name).toBe(admissionIntake);
    expect(current?.placement_intake_name).toBe(earlierIntake);

    const admissions = (await expectOk(
      await page.request.get(
        `${API_BASE}/api/v1/students/${studentId}/admissions`,
      ),
      200,
    )) as { items: { admission_intake_name: string }[] };
    expect(admissions.items[0].admission_intake_name).toBe(admissionIntake);

    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
    await login(page, USERS.teacher);
    await page.goto(app(`/app/students/${studentId}`));
    await expect(
      page.getByText("You do not have permission to do this."),
    ).toBeVisible();
    const teacherAttempt = await page.request.post(
      `${API_BASE}/api/v1/students/${studentId}/placements`,
      {
        data: {
          admission_id: admission.id,
          program_offering_id: offerings.later,
        },
      },
    );
    expect(teacherAttempt.status()).toBe(403);
  });

  test("arabic profile mirrors the placement panel and its history", async ({ page }) => {
    test.setTimeout(120_000);
    await login(page, USERS.admin, "/ar");
    await page.goto(`/ar/app/students/${studentId}`);
    await page.getByRole("tab", { name: "الأكاديمي", exact: true }).click();

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    const panel = page.locator("section").filter({
      has: page.getByRole("heading", {
        name: "التوزيع الأكاديمي",
        exact: true,
      }),
    });
    await expect(panel).toBeVisible();
    await expect(panel.getByText("دفعة القبول الأصلية")).toBeVisible();
    await expect(panel.getByText("توزيع في دفعة أسبق")).toBeVisible();
    await expect(
      panel.getByText("E2E approved catch-up teaching placement"),
    ).toBeVisible();
    await expect(panel.locator("ol > li")).toHaveCount(2);

    const box = await panel.boundingBox();
    const main = page.locator("main").first();
    const mainBox = await main.boundingBox();
    expect(box).not.toBeNull();
    expect(mainBox).not.toBeNull();
    if (box && mainBox) {
      expect(box.width).toBeLessThanOrEqual(mainBox.width + 1);
      expect(box.x).toBeGreaterThanOrEqual(mainBox.x);
    }
  });

  test("audit log names and filters each placement action", async ({ page }) => {
    test.setTimeout(120_000);
    await login(page, USERS.admin);
    await page.goto(app("/app/audit"));

    const labels = [
      ["academic.placement.created", "Academic placement created"],
      ["academic.placement.superseded", "Academic placement superseded"],
      [
        "academic.placement.earlier_intake_authorized",
        "Earlier-intake placement authorized",
      ],
    ] as const;
    const actionFilter = page.getByLabel("Action", { exact: true });
    for (const [code, label] of labels) {
      await expect(actionFilter.locator(`option[value="${code}"]`)).toHaveText(
        label,
      );
      await actionFilter.selectOption(code);
      await expect(
        page.getByRole("row").filter({ hasText: label }).first(),
      ).toBeVisible();
    }

    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
    await login(page, USERS.admin, "/ar");
    await page.goto("/ar/app/audit");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    const arabicAction = page.getByLabel("الإجراء", { exact: true });
    await expect(
      arabicAction.locator(
        'option[value="academic.placement.earlier_intake_authorized"]',
      ),
    ).toHaveText("تم تفويض توزيع في دفعة أسبق");
    await arabicAction.selectOption(
      "academic.placement.earlier_intake_authorized",
    );
    await expect(
      page
        .getByRole("row")
        .filter({ hasText: "تم تفويض توزيع في دفعة أسبق" })
        .first(),
    ).toBeVisible();
  });
});
