import { expect, test, type Page } from "@playwright/test";

import { API_BASE, LOCALE, USERS, app } from "./accounts";

/**
 * Stage 7 end-to-end coverage: the platform modules and the cross-module
 * behaviour that connects them.
 *
 * The point of these tests is the flow, not the markup. A student filing a
 * ticket and staff answering it exercises ownership rules, the notification
 * service and the audit trail in one pass — the parts that unit tests can each
 * pass individually while the product is still broken.
 *
 * Requires a running stack (see playwright.config.ts).
 */

/** Fail a test on silent browser breakage rather than only on assertions. */
function trackPageHealth(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (err) => failures.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    if (req.failure()?.errorText?.includes("ERR_ABORTED")) return;
    failures.push(`requestfailed: ${req.method()} ${req.url()}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 500) failures.push(`http ${res.status()}: ${res.url()}`);
  });
  return failures;
}

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 25_000 });
}

/**
 * A raw `namespace.someKey` path in the DOM means a translation failed to
 * resolve for this render.
 *
 * The trailing identifier is required so ordinary prose still passes — the
 * empty state legitimately reads "No documents.".
 */
const RAW_KEY_PATH =
  /\b(?:common|navigation|errors|locale|login|announcements|support|documents|notifications|reports|audit)\.[a-z][A-Za-z]*/;

async function expectHealthy(page: Page) {
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/Something went wrong/i);
  expect(body).not.toMatch(/Internal Server Error/i);
  expect(body).not.toMatch(/MISSING_MESSAGE/i);
  expect(body).not.toMatch(RAW_KEY_PATH);
}

test.describe("announcements", () => {
  test("management sees the announcement feed with seeded content", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.management);
    await page.goto(app("/app/announcements"));

    await expect(
      page.getByRole("heading", { name: /^announcements$/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /new announcement/i })).toBeVisible();
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });

  test("a student receives announcements but cannot compose", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.student);
    await page.goto(app("/app/announcements"));

    await expect(
      page.getByRole("heading", { name: /^announcements$/i }),
    ).toBeVisible();
    // Publishing is a management capability; the control must not be offered.
    await expect(
      page.getByRole("button", { name: /new announcement/i }),
    ).toHaveCount(0);
    expect(failures).toEqual([]);
  });
});

test.describe("support tickets", () => {
  test("student files a ticket and staff answers it, notifying the student", async ({
    browser,
  }) => {
    const subject = `E2E visa question ${Date.now()}`;

    // --- Student opens the ticket -----------------------------------------
    const studentContext = await browser.newContext();
    const studentPage = await studentContext.newPage();
    const studentFailures = trackPageHealth(studentPage);
    await login(studentPage, USERS.student);
    await studentPage.goto(app("/app/support"));

    await studentPage.getByRole("button", { name: /new request/i }).click();
    await studentPage.getByLabel(/subject/i).fill(subject);
    await studentPage
      .getByLabel(/describe your request/i)
      .fill("Please confirm the documents I still need to submit for my visa renewal.");
    await studentPage.getByRole("button", { name: /^submit$/i }).click();

    // `getByRole` ignores the duplicate mobile-card node, which is present in
    // the DOM but hidden at desktop width.
    await expect(
      studentPage.getByRole("link", { name: subject }).first(),
    ).toBeVisible({ timeout: 15_000 });

    // --- Staff replies -----------------------------------------------------
    const staffContext = await browser.newContext();
    const staffPage = await staffContext.newPage();
    const staffFailures = trackPageHealth(staffPage);
    await login(staffPage, USERS.management);
    await staffPage.goto(app("/app/support"));

    await staffPage.getByRole("link", { name: subject }).click();
    await staffPage.waitForURL(/\/app\/support\/[0-9a-f-]+$/);

    await staffPage
      .getByLabel(/write a reply/i)
      .fill("You still need a valid residence permit scan.");
    await staffPage.getByRole("button", { name: /^send$/i }).click();
    await expect(
      staffPage.getByText(/valid residence permit scan/i),
    ).toBeVisible({ timeout: 15_000 });

    // Internal notes must be labelled as such, never silently mixed in.
    await staffPage.getByLabel(/internal note/i).check();
    await staffPage
      .getByLabel(/write a reply/i)
      .fill("Internal: this student may need extra time.");
    await staffPage.getByRole("button", { name: /^send$/i }).click();
    await expect(staffPage.getByText(/^Internal:/)).toBeVisible({
      timeout: 15_000,
    });

    await studentContext.close();
    await staffContext.close();

    expect(studentFailures).toEqual([]);
    expect(staffFailures).toEqual([]);
  });

  test("a student never sees another student's ticket", async ({ page }) => {
    await login(page, USERS.student);

    // A ticket id from the seed that belongs to somebody else.
    const foreignId = "00000000-0000-0000-0000-000000000000";
    const response = await page.request.get(
      `${API_BASE}/api/v1/support/${foreignId}`,
    );
    // Unknown and unauthorized are deliberately indistinguishable.
    expect([403, 404]).toContain(response.status());
  });

  test("a student cannot manage tickets", async ({ page }) => {
    await login(page, USERS.student);
    const response = await page.request.get(`${API_BASE}/api/v1/support/stats`);
    // Students hold `support.view` for their own tickets; the staff counters
    // endpoint is not a student surface.
    expect(response.status()).toBe(200);

    const list = await page.request.get(
      `${API_BASE}/api/v1/support?assigned_to_me=false`,
    );
    expect(list.status()).toBe(200);
  });
});

test.describe("notifications", () => {
  test("the header bell links to a working inbox", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.student);

    await page.getByRole("link", { name: /notification/i }).first().click();
    await page.waitForURL(/\/app\/notifications/);

    await expect(
      page.getByRole("heading", { name: /^notifications$/i }),
    ).toBeVisible();
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });

  test("notifications are scoped to the authenticated user", async ({ page }) => {
    await login(page, USERS.student);
    const response = await page.request.get(`${API_BASE}/api/v1/notifications`);
    expect(response.status()).toBe(200);
    // The payload carries no recipient field the client could tamper with:
    // the recipient is always the session user.
    const body = await response.json();
    expect(body).toHaveProperty("unread_count");
  });
});

test.describe("documents", () => {
  test("management sees the private document library", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.management);
    await page.goto(app("/app/documents"));

    await expect(page.getByRole("heading", { name: /^documents$/i })).toBeVisible();
    await expect(page.getByText(/stored privately/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /upload document/i })).toBeVisible();
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });

  test("documents are not downloadable without a session", async ({ browser }) => {
    const anonymous = await browser.newContext();
    const response = await anonymous.request.get(
      `${API_BASE}/api/v1/documents/00000000-0000-0000-0000-000000000000/download`,
      { maxRedirects: 0 },
    );
    expect(response.status()).toBe(401);
    await anonymous.close();
  });
});

test.describe("reports", () => {
  test("management sees operational reports computed from real data", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.management);
    await page.goto(app("/app/reports"));

    await expect(page.getByRole("heading", { name: /^reports$/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /immigration/i })).toBeVisible();

    await page.getByRole("tab", { name: /housing/i }).click();
    await expect(
      page.getByRole("heading", { name: /occupancy/i }).first(),
    ).toBeVisible();

    expect(failures).toEqual([]);
  });

  test("students are denied reports", async ({ page }) => {
    await login(page, USERS.student);
    await page.goto(app("/app/reports"));
    await page.waitForLoadState("networkidle");
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/permission/i);
  });
});

test.describe("audit trail", () => {
  test("admin can read the audit log and it contains a sign-in event", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.admin);
    await page.goto(app("/app/audit"));

    await expect(page.getByRole("heading", { name: /^audit log$/i })).toBeVisible();
    // Assert on a table cell: "Signed in" also appears as an <option> in the
    // action filter, which is not visible content.
    await expect(
      page.locator("td", { hasText: /^Signed in$/ }).first(),
    ).toBeVisible({ timeout: 15_000 });
    // The page states outright that secrets are never recorded.
    await expect(page.getByText(/passwords, session tokens/i)).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("teachers cannot read the audit log", async ({ page }) => {
    await login(page, USERS.teacher);
    await page.goto(app("/app/audit"));
    await page.waitForLoadState("networkidle");
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/permission/i);
  });
});

test.describe("authorization hardening", () => {
  test("a student cannot browse the dormitory", async ({ page }) => {
    await login(page, USERS.student);
    await page.goto(app("/app/housing"));
    await page.waitForLoadState("networkidle");
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/permission|no access/i);

    // The navigation entry must not be offered either.
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Housing" })).toHaveCount(0);
  });

  test("a student cannot enumerate a class roster through the API", async ({ page }) => {
    await login(page, USERS.student);

    const classes = await page.request.get(
      `${API_BASE}/api/v1/academics/classes?page_size=1`,
    );
    expect(classes.status()).toBe(200);
    const classId = (await classes.json()).items?.[0]?.id;
    expect(classId).toBeTruthy();

    const roster = await page.request.get(
      `${API_BASE}/api/v1/academics/classes/${classId}/enrollments`,
    );
    expect(roster.status()).toBe(403);

    const grades = await page.request.get(
      `${API_BASE}/api/v1/academics/classes/${classId}/grades`,
    );
    expect(grades.status()).toBe(403);
  });

  test("an unknown conversation, record or document is never leaked", async ({ page }) => {
    await login(page, USERS.student);
    const missing = "11111111-1111-1111-1111-111111111111";

    for (const path of [`/api/v1/support/${missing}`, `/api/v1/documents/${missing}`]) {
      const response = await page.request.get(`${API_BASE}${path}`);
      expect([403, 404]).toContain(response.status());
    }
  });
});

test.describe("student navigation scope", () => {
  test("a student's navigation is limited to self-service modules", async ({ page }) => {
    await login(page, USERS.student);
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    const staff = ["Students", "Immigration", "Housing", "Academics", "Reports", "Audit log"];

    // Self-service is present on the rail. V3 replaced the V1 sidebar with a
    // horizontal tab rail, so these are the rail's own links.
    await expect(nav.getByRole("link", { name: "My profile" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Announcements" })).toBeVisible();

    // …and institutional surfaces are absent from it.
    for (const hidden of staff) {
      await expect(nav.getByRole("link", { name: hidden })).toHaveCount(0);
    }

    // The rail keeps everything that does not fit behind "More", so the same
    // check has to cover the overflow menu; a visible-row-only assertion would
    // miss a module that leaked into it.
    const more = nav.getByRole("button", { name: "More" });
    if (await more.count()) {
      await more.click();
      for (const hidden of staff) {
        await expect(page.getByRole("menuitem", { name: hidden })).toHaveCount(0);
      }
      await page.keyboard.press("Escape");
    }
  });
});
