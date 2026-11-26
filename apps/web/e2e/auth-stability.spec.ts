import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { LOCALE, USERS, app } from "./accounts";

/**
 * Authentication stability — the "randomly logged out" regression.
 *
 * The reported symptom was not a server-side expiry. Two installations on the
 * same host (V1 on :8000, V3 on :8001) both issued a cookie named
 * `session_token`; cookies are host-scoped and ignore the port, so signing in
 * to one replaced the other's session. The browser still rendered the portal
 * from its in-memory identity while every request answered 401, and only
 * signing out and in again repaired it.
 *
 * These tests assert the properties that must hold for that class of failure
 * to be handled correctly, whatever caused it:
 *
 *   - a live session survives navigation, refresh and a second tab;
 *   - a transient network failure neither destroys the session nor shows the
 *     login screen;
 *   - a 403 is a permission answer, not a session end;
 *   - a genuinely dead session produces one controlled redirect to the login
 *     page with an explanation, never a zombie shell;
 *   - the cookie name is namespaced.
 */

const COOKIE_NAME = "sycumain_session";

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 30_000 });
}

async function expectAuthenticated(page: Page) {
  // The account menu trigger only exists once an identity has been restored,
  // so it is a stronger signal than "the URL looks right".
  await expect(page.locator("header .scu-me").first()).toBeVisible({ timeout: 20_000 });
  await expect(page).not.toHaveURL(/\/login/);
}

/** Replace the session cookie with a value the server cannot resolve. */
async function clobberSessionCookie(context: BrowserContext) {
  const cookies = await context.cookies();
  const session = cookies.find((cookie) => cookie.name === COOKIE_NAME);
  expect(session, "login must issue the namespaced session cookie").toBeTruthy();
  await context.addCookies([
    { ...session!, value: "invalid-session-value-from-another-installation" },
  ]);
}

test.describe("authentication stability", () => {
  test("login → modules → refresh keeps the same session", async ({ page }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    for (const path of ["/app/students", "/app/academics", "/app/housing", "/app/immigration"]) {
      await page.goto(app(path));
      await expectAuthenticated(page);
      await expect(page.locator("main")).toBeVisible();
    }

    // A full page load re-runs the session bootstrap from the cookie alone.
    await page.goto(app("/app/housing"));
    await page.reload();
    await expectAuthenticated(page);
    await expect(page.getByRole("heading", { name: /housing/i }).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("a second tab shares the session; signing out ends it for both", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    const second = await context.newPage();
    await second.goto(app("/app/students"));
    await expectAuthenticated(second);

    // Sign out from the first tab.
    //
    // The shell's account-menu path is exercised by `smoke.spec.ts` and by
    // every spec that calls `signOutViaAccountMenu`. Here the menu is a
    // portalled, animated overlay that can be re-rendered by the notification
    // poll mid-click, which makes this particular test racy for reasons that
    // have nothing to do with what it asserts. Issuing the same request the
    // button issues keeps the assertion on the session itself: does the second
    // tab lose access, and does it recover cleanly?
    const logoutStatus = await page.evaluate(async (apiBase) => {
      const response = await fetch(`${apiBase}/api/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      return response.status;
    }, process.env.E2E_API_URL ?? "http://localhost:8001");
    expect(logoutStatus).toBe(200);

    // The other tab still holds a rendered identity, but its session is gone.
    // Its next request must produce a controlled redirect, not an error pile.
    await second.goto(app("/app/students"));
    await second.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });

    await second.close();
  });

  test("a dead session redirects to login with an explanation", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    // Simulate the reported failure exactly: the app is loaded and believes it
    // is signed in, then the cookie stops resolving (another installation on
    // this host overwrote it, or the session was revoked elsewhere).
    await clobberSessionCookie(context);

    // Client-side navigation keeps the React state intact — the zombie state
    // that used to require a manual sign-out. The redirect may already have
    // happened by the time this click is attempted, because the dashboard's
    // own background requests (the notification poll) carry the same dead
    // cookie. Either route to the redirect is correct, so the click is
    // best-effort and the assertion is on the outcome.
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await nav
      .getByRole("link", { name: "Students" })
      .first()
      .click({ timeout: 8_000 })
      .catch(() => undefined);

    // The 401 must be re-checked against /auth/me and then resolved into one
    // redirect, with the reason stated rather than requiring a manual logout.
    await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
    await expect(page.getByText(/session has expired/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("header .scu-me")).toHaveCount(0);
  });

  test("a permission refusal is not treated as a session end", async ({ page }) => {
    await login(page, USERS.student);

    // The student role has no `student.view`; the API answers 403 and the page
    // renders a permission message. That must not sign the user out.
    await page.goto(app("/app/students"));
    await page.waitForLoadState("networkidle");
    await expectAuthenticated(page);
    await expect(page.getByText(/permission|cannot access|no access/i).first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("a network interruption keeps the session and recovers", async ({
    page,
    context,
  }) => {
    await login(page, USERS.admin);
    await expectAuthenticated(page);

    // Every API call fails at the transport layer while the banner is up.
    await context.route("**/api/v1/**", (route) => route.abort("failed"));
    await page.reload();

    // Not signed out: the guard offers a retry instead of the login screen.
    await expect(page.getByRole("heading", { name: /network error/i })).toBeVisible({
      timeout: 25_000,
    });
    await expect(page).not.toHaveURL(/\/login/);

    // Reconnecting and retrying restores the same session — no second login.
    await context.unroute("**/api/v1/**");
    await page.getByRole("button", { name: /try again/i }).click();
    await expectAuthenticated(page);
    await expect(page.getByRole("heading", { name: /welcome/i })).toBeVisible({
      timeout: 20_000,
    });
  });
});
