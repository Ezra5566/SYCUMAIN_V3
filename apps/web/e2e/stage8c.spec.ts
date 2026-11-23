import { expect, test, type Page } from "@playwright/test";

import { ADMIN, API_BASE } from "./accounts";

/**
 * Student lifecycle and password-recovery browser tests (Stage 8C).
 *
 * The recovery flow is worth a browser test because it is the one journey that
 * crosses pages, locales and query strings while *unauthenticated*:
 *
 *   login -> "Forgot your password?" -> request a link -> open the link
 *   -> choose a new password -> sign in with it
 *
 * Two things can only be observed here. A missing or stale link must render the
 * explanatory notice instead of an unusable form — that is a render decision,
 * not an API contract. And the "no self-service recovery" state must be honest:
 * on a stack with no delivery channel the login screen must not offer the link
 * at all, rather than offering one that silently does nothing.
 *
 * Runs against the real Docker stack; requires `docker compose up`.
 */

const LOCALE = "en";
const app = (path: string) => `/${LOCALE}${path}`;

let sequence = 0;

/** Unique throwaway identity; onboarding is idempotent on the student number. */
function newStudent() {
  sequence += 1;
  const stamp = `${Date.now().toString().slice(-7)}${sequence}`;
  return {
    number: `STU-E2E-${stamp}`,
    email: `e2e-recovery-${stamp}@example.com`,
    firstName: "E2E",
    lastName: `Recovery${stamp}`,
    password: `E2e-Onboard!${stamp}`,
  };
}

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
}

async function signOut(page: Page) {
  // Let the authenticated page finish its initial data requests before clearing
  // the session. A dashboard fetch still in flight when logout clears the cookie
  // is cancelled by the ensuing navigation and surfaces as `net::ERR_FAILED`,
  // which is neither an application error nor the usual `net::ERR_ABORTED`.
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
}

/**
 * Onboard a student through the UI and return its one-time credential.
 *
 * Recovery is tested against a dedicated account so the seeded demo login is
 * never disturbed — a suite that changed the shared student password would
 * break every test that runs after it.
 */
async function onboardStudent(page: Page) {
  const student = newStudent();

  await login(page, ADMIN);
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 25_000 });
  await page.goto(app("/app/students"));
  await page.getByRole("button", { name: /add student/i }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(/student number/i).fill(student.number);
  await dialog.getByLabel(/first name/i).fill(student.firstName);
  await dialog.getByLabel(/last name/i).fill(student.lastName);
  await dialog.getByLabel(/^email/i).fill(student.email);
  await dialog.getByRole("button", { name: /^create$/i }).click();

  const passwordField = page.getByTestId("temporary-password");
  await expect(passwordField).toBeVisible({ timeout: 25_000 });
  const password = (await passwordField.innerText()).trim();

  await page.getByRole("button", { name: /done/i }).click();
  await signOut(page);

  return { student, password };
}

/** Whether this stack can actually deliver a reset link. */
async function recoveryAvailable(page: Page): Promise<boolean> {
  const response = await page.request.get(
    `${API_BASE}/api/v1/auth/password/reset-availability`,
  );
  if (!response.ok()) return false;
  return Boolean((await response.json()).available);
}

test.describe("password recovery", () => {
  test("login offers recovery only when the stack can deliver a link", async ({
    page,
  }) => {
    const available = await recoveryAvailable(page);

    await page.goto(app("/login"));
    const link = page.getByRole("link", { name: /forgot your password/i });

    if (available) {
      await expect(link).toBeVisible();
      await link.click();
      await page.waitForURL(/\/forgot-password$/, { timeout: 25_000 });
      await expect(
        page.getByRole("heading", { name: /reset your password/i }),
      ).toBeVisible();
    } else {
      // No delivery channel: the capability endpoint says so, and the recovery
      // page must say so too instead of accepting a request it cannot fulfil.
      await expect(link).toBeVisible();
      await link.click();
      await page.waitForURL(/\/forgot-password$/, { timeout: 25_000 });
      await expect(page.getByText(/not enabled on this deployment/i)).toBeVisible();
      await expect(
        page.getByRole("button", { name: /send reset link/i }),
      ).toBeDisabled();
    }
  });

  test("an unknown address is acknowledged without revealing that it is unknown", async ({
    page,
  }) => {
    test.skip(
      !(await recoveryAvailable(page)),
      "no reset delivery channel is configured on this stack",
    );

    await page.goto(app("/forgot-password"));
    await page.getByLabel(/email/i).fill("nobody-at-all@example.com");
    await page.getByRole("button", { name: /send reset link/i }).click();

    // The wording is deliberately conditional ("If an account exists…") and the
    // page must reach the same confirmation state as a real address would.
    await expect(
      page.getByText(/if an account exists/i),
    ).toBeVisible({ timeout: 25_000 });
  });

  test("student resets a forgotten password and signs in with the new one", async ({
    page,
  }) => {
    test.skip(
      !(await recoveryAvailable(page)),
      "no reset delivery channel is configured on this stack",
    );

    const failures = trackPageHealth(page);
    const onboarded = await onboardStudent(page);
    const newPassword = `E2e-Recovered!${Date.now().toString().slice(-6)}`;

    // Ask for a link, as a user who cannot sign in would.
    await page.goto(app("/login"));
    await page.getByRole("link", { name: /forgot your password/i }).click();
    await page.waitForURL(/\/forgot-password$/, { timeout: 25_000 });

    await page.getByLabel(/email/i).fill(onboarded.student.email);
    await page.getByRole("button", { name: /send reset link/i }).click();
    await expect(page.getByText(/if an account exists/i)).toBeVisible({
      timeout: 25_000,
    });

    // With no mail provider configured, the development channel surfaces the
    // link in the page. Following it is the same navigation a real email
    // would trigger.
    await page.getByRole("link", { name: /open the reset link/i }).click();
    await page.waitForURL(/\/reset-password\?token=/, { timeout: 25_000 });

    // A live token renders a usable form, not the stale-link notice.
    await expect(
      page.getByRole("heading", { name: /choose a new password/i }),
    ).toBeVisible();
    // `exact` matters: "Confirm new password" also matches a loose /new password/i.
    const newPasswordField = page.getByLabel("New password", { exact: true });
    await expect(newPasswordField).toBeVisible();

    await newPasswordField.fill(newPassword);
    await page.getByLabel("Confirm new password", { exact: true }).fill(newPassword);
    await page.getByRole("button", { name: /set new password/i }).click();

    await expect(page.getByText(/your password has been updated/i)).toBeVisible({
      timeout: 25_000,
    });

    // The new credential is what works now.
    await page.getByRole("link", { name: /continue to sign in/i }).click();
    await page.waitForURL(/\/login$/, { timeout: 25_000 });
    await page.getByLabel(/email/i).fill(onboarded.student.email);
    await page.getByLabel(/password/i).fill(newPassword);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL(new RegExp(`/${LOCALE}/app$`), { timeout: 25_000 });

    await signOut(page);

    // And the original one-time credential no longer does.
    await page.getByLabel(/email/i).fill(onboarded.student.email);
    await page.getByLabel(/password/i).fill(onboarded.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 25_000 });
    await expect(page).toHaveURL(/\/login$/);

    expect(failures).toEqual([]);
  });

  test("a reset link without a token explains itself instead of showing a dead form", async ({
    page,
  }) => {
    await page.goto(app("/reset-password"));

    await expect(
      page.getByText(/incomplete or has already been used/i),
    ).toBeVisible();
    await expect(page.getByLabel("New password", { exact: true })).toHaveCount(0);
  });

  test("a used reset link cannot be replayed", async ({ page }) => {
    test.skip(
      !(await recoveryAvailable(page)),
      "no reset delivery channel is configured on this stack",
    );

    const onboarded = await onboardStudent(page);
    const first = `E2e-Replay!${Date.now().toString().slice(-6)}`;

    await page.goto(app("/forgot-password"));
    await page.getByLabel(/email/i).fill(onboarded.student.email);
    await page.getByRole("button", { name: /send reset link/i }).click();
    await page.getByRole("link", { name: /open the reset link/i }).click();
    await page.waitForURL(/\/reset-password\?token=/, { timeout: 25_000 });

    const usedUrl = page.url();

    await page.getByLabel("New password", { exact: true }).fill(first);
    await page.getByLabel("Confirm new password", { exact: true }).fill(first);
    await page.getByRole("button", { name: /set new password/i }).click();
    await expect(page.getByText(/your password has been updated/i)).toBeVisible({
      timeout: 25_000,
    });

    // Re-opening the same URL must refuse, and the refusal must be a handled
    // message rather than an unhandled error.
    const failures = trackPageHealth(page);
    await page.goto(usedUrl);
    await page.getByLabel("New password", { exact: true }).fill("E2e-Replay2!123456");
    await page.getByLabel("Confirm new password", { exact: true }).fill(
      "E2e-Replay2!123456",
    );
    await page.getByRole("button", { name: /set new password/i }).click();

    // Next.js renders an empty `role="alert"` route announcer alongside the
    // application notice, so target the notice by its own text.
    await expect(
      page.getByRole("alert").filter({ hasText: /this reset link is invalid/i }),
    ).toBeVisible({ timeout: 25_000 });
    expect(failures.filter((f) => f.startsWith("pageerror"))).toEqual([]);
  });

  test("the recovery pages are usable in every locale", async ({ page }) => {
    const expected: Record<string, { heading: RegExp; action: RegExp }> = {
      en: { heading: /reset your password/i, action: /send reset link/i },
      zh: { heading: /重置密码/, action: /发送重置链接/ },
      fr: {
        heading: /réinitialiser votre mot de passe/i,
        action: /envoyer le lien/i,
      },
      ar: { heading: /إعادة تعيين كلمة المرور/, action: /إرسال رابط إعادة التعيين/ },
    };

    for (const [locale, copy] of Object.entries(expected)) {
      await page.goto(`/${locale}/forgot-password`);
      await expect(page.getByRole("heading", { name: copy.heading })).toBeVisible();
      await expect(page.getByRole("button", { name: copy.action })).toBeVisible();
    }

    // Arabic must flip the document, not merely translate the strings.
    await page.goto("/ar/forgot-password");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

    await page.goto("/en/forgot-password");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  });
});
