import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { LOCALE, USERS, app } from "./accounts";

/**
 * Focused authentication certification for the Phase 8 release baseline.
 *
 * Session cookie namespacing, the client session lifecycle rewrite and the
 * global origin guard all changed browser behaviour, so these are the
 * behaviours that were exercised — not the whole historical suite.
 *
 * The properties asserted are the ones a person would notice:
 *
 *   - a valid session survives navigation, a full reload and a second tab;
 *   - components appear without signing out and back in;
 *   - one failed request, a transport failure or a permission refusal does not
 *     end the session;
 *   - a genuinely dead session ends once, with an explanation;
 *   - an explicit sign-out really invalidates the session on the server;
 *   - all five locales work, and Arabic is right-to-left;
 *   - the server still enforces role permissions.
 *
 * Run against the live development stack:
 *
 *   E2E_BASE_URL=http://localhost:3101 E2E_API_URL=http://localhost:8001 \
 *     E2E_PASSWORD='<demo password>' \
 *     npx playwright test e2e/phase8-auth-certification.spec.ts --project=chromium
 */

const API = process.env.E2E_API_URL ?? "http://localhost:8001";
const COOKIE_NAME = "sycumain_session";

const PROTECTED_MODULES = [
  "/app",
  "/app/students",
  "/app/academics",
  "/app/housing",
  "/app/immigration",
  "/app/announcements",
  "/app/reports",
];

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 30_000 });
}

/** The account menu exists only once an identity has been restored. */
async function expectAuthenticated(page: Page) {
  await expect(page.locator("header .scu-me").first()).toBeVisible({ timeout: 25_000 });
  await expect(page).not.toHaveURL(/\/login/);
}

/**
 * Sign out through the account menu with the pointer.
 *
 * `accounts.ts` drives the same menu from the keyboard, which is the path a
 * keyboard user takes and the one `smoke.spec.ts` certifies. Here the pointer is
 * used deliberately: the menu is portalled and re-rendered by the notification
 * poll, and focus can be taken from the trigger between the keypress and the
 * menu opening — a harness interaction problem that says nothing about whether
 * sign-out works. Playwright re-checks stability before a click, so a re-render
 * during the animation is retried instead of lost.
 */
async function signOutWithPointer(page: Page) {
  await expectAuthenticated(page);
  await page.locator("header .scu-me").first().click();
  const item = page.getByRole("menuitem", { name: /sign out/i });
  await expect(item).toBeVisible({ timeout: 20_000 });
  await item.click();
  await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
}

async function sessionCookie(context: BrowserContext) {
  const cookie = (await context.cookies()).find((item) => item.name === COOKIE_NAME);
  expect(cookie, "sign-in must issue the namespaced session cookie").toBeTruthy();
  return cookie!;
}

test.describe("phase 8 authentication certification", () => {
  test("fresh login initializes the dashboard and renders its components", async ({ page }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    // Identity, navigation and content are all present after the first load —
    // the reported symptom was a shell that needed a re-login to fill in.
    await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("heading", { name: /welcome/i }).first()).toBeVisible({
      timeout: 20_000,
    });

    const me = await page.evaluate(async (apiBase) => {
      const response = await fetch(`${apiBase}/api/v1/auth/me`, { credentials: "include" });
      return response.status;
    }, API);
    expect(me).toBe(200);
  });

  test("navigation between protected modules keeps the session and renders each surface", async ({
    page,
  }) => {
    await login(page, USERS.admin);

    for (const path of PROTECTED_MODULES) {
      await page.goto(app(path));
      await expectAuthenticated(page);
      await expect(page.locator("main")).toBeVisible();
      // Each module renders its own heading; an empty shell would not.
      await expect(page.locator("main h1, main h2").first()).toBeVisible({ timeout: 20_000 });
    }
  });

  test("a refresh, a second tab and returning to the first tab share one session", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    const original = (await sessionCookie(context)).value;

    await page.goto(app("/app/housing"));
    await page.reload();
    await expectAuthenticated(page);
    await expect(page.getByRole("heading", { name: /housing/i }).first()).toBeVisible({
      timeout: 20_000,
    });

    const second = await context.newPage();
    await second.goto(app("/app/students"));
    await expectAuthenticated(second);

    // Returning to the original tab uses the same cookie in the same context.
    await page.bringToFront();
    await expectAuthenticated(page);
    expect((await sessionCookie(context)).value).toBe(original);

    await second.close();
  });

  test("a transport failure is not an expiry and recovers without signing in again", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    await context.route("**/api/v1/**", (route) => route.abort("failed"));
    await page.reload();

    await expect(page.getByRole("heading", { name: /network error/i })).toBeVisible({
      timeout: 25_000,
    });
    await expect(page).not.toHaveURL(/\/login/);

    await context.unroute("**/api/v1/**");
    await page.getByRole("button", { name: /try again/i }).click();
    await expectAuthenticated(page);
    await expect(page.getByRole("heading", { name: /welcome/i }).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("a single 401 from a background request does not end a valid session", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    let intercepted = 0;
    await context.route("**/api/v1/notifications**", async (route) => {
      if (intercepted === 0) {
        intercepted += 1;
        await route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "UNAUTHORIZED", message: "Your session has expired." },
          }),
        });
        return;
      }
      await route.fallback();
    });

    await page.goto(app("/app/announcements"));
    await page.waitForLoadState("networkidle");

    // Still signed in: one rejected request is a request failure, not a logout.
    await expectAuthenticated(page);
    expect(intercepted, "the notification request must have been exercised").toBeGreaterThan(0);

    // And a full re-bootstrap from the cookie still succeeds.
    await context.unroute("**/api/v1/notifications**");
    await page.reload();
    await expectAuthenticated(page);
  });

  test("a 403 is an authorization answer, not a logout", async ({ page }) => {
    await login(page, USERS.student);

    // The student role has no `student.view`.
    await page.goto(app("/app/students"));
    await page.waitForLoadState("networkidle");

    await expectAuthenticated(page);
    await expect(page.getByText(/permission|cannot access|no access/i).first()).toBeVisible({
      timeout: 20_000,
    });

    // The session is still usable for the surfaces the student may see.
    await page.goto(app("/app"));
    await expectAuthenticated(page);
  });

  test("a dead session redirects to login once, with an explanation", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    const cookie = await sessionCookie(context);

    await context.addCookies([
      { ...cookie, value: "invalid-session-value-from-another-installation" },
    ]);

    await page.goto(app("/app/students"));
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
    await expect(page.getByText(/session has expired/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("header .scu-me")).toHaveCount(0);
  });

  test("explicit logout invalidates the session server-side, and signing in again works", async ({
    page,
    context,
    playwright,
  }) => {
    await login(page, USERS.admin);
    const cookie = await sessionCookie(context);

    await signOutWithPointer(page);
    await expect(page).toHaveURL(new RegExp(`/${LOCALE}/login`));
    // An explicit sign-out is not an expiry: the page must not claim one.
    await expect(page.getByText(/session has expired/i)).toHaveCount(0);

    // The value the browser held must no longer resolve. Replayed through an
    // API context, because a browser fetch cannot set a Cookie header (it is a
    // forbidden header), which would make this check pass without testing it.
    const replay = await playwright.request.newContext({
      extraHTTPHeaders: { cookie: `${COOKIE_NAME}=${cookie.value}` },
    });
    const replayed = await replay.get(`${API}/api/v1/auth/me`);
    expect(replayed.status()).toBe(401);
    await replay.dispose();

    // Protected routes now require a sign-in rather than showing a shell.
    await page.goto(app("/app"));
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });

    await login(page, USERS.admin);
    await expectAuthenticated(page);
  });

  test("all five locales keep the session, and Arabic is right-to-left", async ({ page }) => {
    await login(page, USERS.admin);

    for (const locale of ["en", "zh", "fr", "ru", "ar"]) {
      await page.goto(`/${locale}/app`);
      await expectAuthenticated(page);

      const direction = await page.evaluate(() => {
        const root = document.documentElement;
        return (root.getAttribute("dir") ?? getComputedStyle(root).direction).toLowerCase();
      });

      if (locale === "ar") {
        expect(direction).toBe("rtl");
      } else {
        expect(direction).toBe("ltr");
      }
    }
  });

  test("role-specific route access is enforced by the server, not the menu", async ({ page }) => {
    // National admin surface: reachable, and it renders its own heading.
    await login(page, USERS.admin);
    await page.goto(app("/app/accounts"));
    await page.waitForLoadState("networkidle");
    await expectAuthenticated(page);
    await expect(page.getByText(/permission|cannot access|no access/i)).toHaveCount(0);
    await expect(page.locator("main h1, main h2").first()).toBeVisible({ timeout: 20_000 });

    await signOutWithPointer(page);
    await login(page, USERS.student);

    // The student's menu does not offer the administration surfaces at all.
    const studentNav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(studentNav.locator('a[href$="/app/accounts"]')).toHaveCount(0);
    await expect(studentNav.locator('a[href$="/app/audit"]')).toHaveCount(0);

    // Hiding the link is not the control: the route itself must refuse, and the
    // refusal must not be mistaken for a lost session.
    await page.goto(app("/app/accounts"));
    await page.waitForLoadState("networkidle");
    await expectAuthenticated(page);
    // The accounts surface states the refusal specifically ("Administrator
    // access required"); the generic permission text is what a 403 from the API
    // renders. Either is a refusal, and neither is a logout.
    await expect(
      page.getByText(/administrator access required|permission|cannot access|no access/i).first(),
    ).toBeVisible({ timeout: 20_000 });
  });
});
