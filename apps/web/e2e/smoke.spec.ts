import { expect, test, type Page } from "@playwright/test";

import { LOCALE, USERS, app } from "./accounts";

/**
 * Critical-path smoke tests.
 *
 * These exist because a green backend test suite does NOT prove the browser
 * experience works. They exercise the real HTTP + cookie + RBAC path end to end
 * against the same artifact that gets deployed.
 *
 * Routes carry a locale prefix, so every path is rooted at `/${LOCALE}`.
 * Multilingual and RTL behaviour is covered separately in `i18n.spec.ts`.
 *
 * Requires a running stack (see playwright.config.ts).
 */

/** Collect browser-level failures so a test fails on silent breakage. */
function trackPageHealth(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (err) => failures.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    // Ignore aborted navigations caused by client-side redirects.
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

async function expectHealthy(page: Page) {
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/Something went wrong/i);
  expect(body).not.toMatch(/Internal Server Error/i);
  expect(body).not.toMatch(/Couldn't load/i);
  // A raw key path means message loading failed for this render.
  expect(body).not.toContain("navigation.");
  expect(body).not.toContain("common.actions.");
}

test.describe("authentication", () => {
  test("login succeeds and lands on the dashboard", async ({ page }) => {
    await login(page, USERS.admin);
    await expect(page).toHaveURL(new RegExp(`/${LOCALE}/app$`));
    await expect(page.getByRole("heading", { name: /welcome/i })).toBeVisible();
  });

  test("anonymous access to a protected page redirects to login", async ({ page }) => {
    await page.goto(app("/app/students"));
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
  });

  test("invalid credentials do not authenticate", async ({ page }) => {
    await page.goto(app("/login"));
    await page.getByLabel(/email/i).fill(USERS.admin.email);
    await page.getByLabel(/password/i).fill("wrong-password");
    await page.getByRole("button", { name: /sign in/i }).click();
    // Wait for the rendered error rather than a fixed delay: the assertion is
    // that the credential was rejected, not that a timer elapsed.
    await expect(page.getByText(/incorrect email or password/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page).not.toHaveURL(/\/app/);
  });

  test("logout returns to login and the session is invalidated", async ({ page }) => {
    await login(page, USERS.admin);
    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });

    // Navigating back must not restore the session.
    await page.goto(app("/app/students"));
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
  });
});

test.describe("staff modules", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, USERS.admin);
  });

  test("student directory lists students", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/students"));
    await expect(page.getByRole("heading", { name: /student directory/i })).toBeVisible();

    // Search rather than reading page 1: the directory is server-paginated and
    // the dataset grows (browser runs onboard students), so a seeded student is
    // not guaranteed to be on the first page.
    await page.getByRole("searchbox", { name: "Search" }).fill("STU-001");
    // The desktop table exposes student numbers as table cells.
    await expect(page.getByRole("cell", { name: "STU-001" })).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("student profile exposes all module tabs", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/students"));
    await page.locator(`a[href*="${app("/app/students/")}"]:visible`).first().click();
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+/);

    for (const tab of ["Overview", "Academic", "Immigration", "Housing", "Timetable"]) {
      await expect(page.getByRole("tab", { name: tab, exact: true })).toBeVisible();
    }

    // Tabs must actually render content.
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });

  test("housing module shows seeded buildings", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/housing"));
    await expect(page.getByRole("heading", { name: /housing/i }).first()).toBeVisible();
    await expect(page.getByText(/Building 18/)).toBeVisible();
    // Occupancy is stated in words, not only by colour.
    await expect(page.getByText(/Occupancy legend/i).first()).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("housing drills down building → floor → room", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/housing"));
    await page.getByText(/Building 18/).click();
    await page.waitForURL(/\/app\/housing\/[0-9a-f-]+$/);
    await expect(page.getByText(/Floor 1/)).toBeVisible();

    await page.getByText(/Floor 1/).first().click();
    await page.waitForURL(/\/app\/housing\/[0-9a-f-]+\/[0-9a-f-]+/);
    await expect(page.getByText(/Room grid/i)).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("room detail lists beds and occupants", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/housing"));
    await page.getByText(/Building 18/).click();
    await page.waitForURL(/\/app\/housing\/[0-9a-f-]+$/);
    await page.getByText(/Floor 1/).first().click();
    await page.waitForURL(/\/app\/housing\/[0-9a-f-]+\/[0-9a-f-]+/);

    // Target a room tile by its accessible name. Selecting by href would also
    // match the building breadcrumb, which links to a shallower path.
    await page.getByRole("link", { name: /^Room / }).first().click();
    await page.waitForURL(/\/app\/housing\/[0-9a-f-]+\/[0-9a-f-]+\/[0-9a-f-]+$/);

    await expect(page.getByRole("heading", { name: /room/i }).first()).toBeVisible();
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });

  test("immigration module loads real expiry data", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/immigration"));
    await expect(page.getByRole("heading", { name: /^immigration$/i })).toBeVisible();
    await expect(page.getByText(/valid/i).first()).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("academics module loads majors, courses and timetable", async ({ page }) => {
    const failures = trackPageHealth(page);
    await page.goto(app("/app/academics"));
    await expect(page.getByRole("heading", { name: /^academics$/i })).toBeVisible();
    await expect(page.getByText(/Computer Science/).first()).toBeVisible();
    await expect(page.getByText(/Introduction to Programming/).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: /^timetable$/i })).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("sidebar navigation shows staff modules for admin", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Students" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Immigration" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Academics" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Housing" })).toBeVisible();
  });
});

test.describe("role scoping", () => {
  test("student is denied the student directory", async ({ page }) => {
    await login(page, USERS.student);
    await page.goto(app("/app/students"));
    await page.waitForLoadState("networkidle");
    const body = await page.locator("body").innerText();
    expect(body).toMatch(/permission|cannot access|no access|forbidden/i);
  });

  test("student does not see staff modules in navigation", async ({ page }) => {
    await login(page, USERS.student);
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Students" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Immigration" })).toHaveCount(0);
  });

  test("teacher can sign in and sees a scoped dashboard", async ({ page }) => {
    await login(page, USERS.teacher);
    await expectHealthy(page);
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Students" })).toBeVisible();
  });

  test("management can reach staff modules", async ({ page }) => {
    const failures = trackPageHealth(page);
    await login(page, USERS.management);
    await page.goto(app("/app/immigration"));
    await expectHealthy(page);
    expect(failures).toEqual([]);
  });
});
