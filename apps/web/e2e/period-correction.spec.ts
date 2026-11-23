import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Phase 5 intake-date correction.
 *
 * Synthetic periods only. The forward and reverse corrections prove the dialog
 * records history rather than silently editing dates, and the Arabic pass
 * checks that both date fields are present and localized in RTL.
 */

async function login(page: Page, user: { email: string; password: string }, locale = "en") {
  await page.goto(`/${locale}/login`);
  await page.getByLabel(/email|البريد/i).fill(user.email);
  await page.getByLabel(/password|كلمة المرور/i).fill(user.password);
  await page.getByRole("button").filter({ hasText: /sign in|تسجيل الدخول/i }).click();
  await page.waitForURL(new RegExp(`/${locale}/app`), { timeout: 25_000 });
}

async function expectOk(response: APIResponse, expected: number) {
  const body = await response.text();
  expect(response.status(), body).toBe(expected);
  return body ? JSON.parse(body) : null;
}

async function createPeriod(page: Page, stamp: string, suffix: string) {
  return (await expectOk(
    await page.request.post(`${API_BASE}/api/v1/academics/periods`, {
      data: {
        name: `E2E correction intake ${stamp}-${suffix}`,
        code: `EC${stamp.slice(-8)}${suffix}`,
        start_date: "2045-09-01",
        end_date: "2045-12-20",
        status: "ACTIVE",
      },
    }),
    201,
  )) as { id: string; name: string };
}

test.describe.serial("intake date correction", () => {
  test("records a forward and reverse correction and keeps its history", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now().toString().slice(-7);
    await login(page, USERS.admin);
    const period = await createPeriod(page, stamp, "F");

    await page.goto(app("/app/academics"));
    const row = page.getByRole("row").filter({ hasText: period.name });
    await expect(row).toBeVisible({ timeout: 25_000 });
    await row.getByRole("button", { name: "Correct dates" }).click();

    let dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Current official dates")).toBeVisible();
    await dialog.getByLabel("New start date").fill("2045-09-10");
    await dialog.getByLabel("New end date").fill("2045-12-15");
    const forwardReason =
      "Registrar confirmed the official dates were transcribed incorrectly.";
    await dialog.getByLabel("Reason").fill(forwardReason);
    await dialog.getByRole("button", { name: "Record correction" }).click();

    await expect(page.getByText("Intake dates corrected")).toBeVisible({
      timeout: 25_000,
    });

    // Saving refetches the table, which briefly replaces it with the loading
    // skeleton and therefore closes this dialog. Reopen it to verify the
    // append-only history the correction just wrote.
    await row.getByRole("button", { name: "Correct dates" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText(forwardReason)).toBeVisible({
      timeout: 25_000,
    });
    await expect(
      dialog.getByText(/1 placement reflagged|No placements reflagged/),
    ).toBeVisible();

    let detail = (await expectOk(
      await page.request.get(`${API_BASE}/api/v1/academics/periods/${period.id}`),
      200,
    )) as { start_date: string; end_date: string };
    expect(detail.start_date).toBe("2045-09-10");
    expect(detail.end_date).toBe("2045-12-15");

    await dialog.getByLabel("New start date").fill("2045-09-01");
    await dialog.getByLabel("New end date").fill("2045-12-20");
    const reverseReason =
      "The original dates were confirmed as correct after review.";
    await dialog.getByLabel("Reason").fill(reverseReason);
    await dialog.getByRole("button", { name: "Record correction" }).click();
    await expect(page.getByText("Intake dates corrected")).toBeVisible({
      timeout: 25_000,
    });
    await row.getByRole("button", { name: "Correct dates" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText(reverseReason)).toBeVisible({
      timeout: 25_000,
    });

    const history = (await expectOk(
      await page.request.get(
        `${API_BASE}/api/v1/academics/periods/${period.id}/date-corrections`,
      ),
      200,
    )) as { reason: string; actor_name: string }[];
    expect(history).toHaveLength(2);
    expect(history[0].reason).toBe(reverseReason);
    expect(history[1].reason).toBe(forwardReason);
    expect(history[0].actor_name).toBe("Admin User");

    detail = (await expectOk(
      await page.request.get(`${API_BASE}/api/v1/academics/periods/${period.id}`),
      200,
    )) as { start_date: string; end_date: string };
    expect(detail.start_date).toBe("2045-09-01");
    expect(detail.end_date).toBe("2045-12-20");
  });

  test("the Arabic dialog is RTL and localizes both mandatory dates", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const stamp = Date.now().toString().slice(-7);
    await login(page, USERS.admin, "ar");
    const period = await createPeriod(page, stamp, "A");

    await page.goto(`/ar/app/academics`);
    const row = page.getByRole("row").filter({ hasText: period.name });
    await expect(row).toBeVisible({ timeout: 25_000 });
    await row.getByRole("button", { name: "تصحيح التواريخ" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(dialog.getByText("التواريخ الرسمية الحالية")).toBeVisible();
    await expect(dialog.getByLabel("تاريخ البدء الجديد")).toBeVisible();
    await expect(dialog.getByLabel("تاريخ الانتهاء الجديد")).toBeVisible();
    await expect(dialog.getByLabel("السبب")).toBeVisible();
  });

  test("teachers and students never see the correction action", async ({ page }) => {
    await login(page, USERS.teacher);
    await page.goto(app("/app/academics"));
    await expect(
      page.getByRole("button", { name: "Correct dates" }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
    await login(page, USERS.student);
    await page.goto(app("/app/academics"));
    await expect(
      page.getByRole("button", { name: "Correct dates" }),
    ).toHaveCount(0);
  });
});
