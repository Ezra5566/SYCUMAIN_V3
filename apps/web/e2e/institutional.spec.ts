import { expect, test, type Page } from "@playwright/test";

import { USERS, app } from "./accounts";

/**
 * Institutional account lifecycle browser coverage.
 *
 * These tests exercise the Admin control surface that the backend governance
 * suite cannot prove: the account list renders real records, a staff login and
 * its linked profile are created together, and a reasoned role change preserves
 * the profile while updating effective access.
 */

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
  await page.waitForURL(new RegExp(`/en/app`), { timeout: 25_000 });
}

test.describe("institutional staff lifecycle", () => {
  test("admin creates a teacher and changes the role with a reason", async ({
    page,
  }) => {
    const failures = trackPageHealth(page);
    const stamp = Date.now().toString().slice(-7);
    const name = `E2E Staff ${stamp}`;
    const email = `e2e-staff-${stamp}@example.com`;
    const department = "International Office";

    await login(page, USERS.admin);
    await page.goto(app("/app/accounts"));
    await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible();
    await expect(page.getByText(USERS.admin.email).first()).toBeVisible();

    await page.getByRole("button", { name: "Create staff account" }).click();
    const create = page.getByRole("dialog");
    await create.getByLabel("Name").fill(name);
    await create.getByLabel("Email").fill(email);
    await create.getByLabel("Department or faculty").fill(department);
    await create.getByRole("button", { name: "Create", exact: true }).click();

    const credential = page.getByRole("dialog");
    await expect(
      credential.getByRole("heading", { name: "Temporary password" }),
    ).toBeVisible();
    await expect(credential.getByText(email)).toBeVisible();
    await credential.getByRole("button", { name: "Done" }).click();

    await page.getByRole("textbox", { name: "Search" }).fill(email);
    const row = page.getByRole("row").filter({ hasText: email });
    await expect(row).toBeVisible();
    await expect(row.getByText("TEACHER", { exact: true })).toBeVisible();
    await expect(row.getByText(department)).toBeVisible();
    await expect(row.getByText("No staff identifier recorded")).toBeVisible();

    await page
      .getByRole("button", { name: `Change role ${name}` })
      .click();
    const roleDialog = page.getByRole("dialog");
    await roleDialog.locator("select").selectOption("MANAGEMENT");
    await roleDialog
      .getByLabel("Reason")
      .fill("Institutional role transition covered by the E2E suite.");
    await roleDialog.getByRole("button", { name: "Save", exact: true }).click();

    await expect(
      page.getByText("The role change has been recorded."),
    ).toBeVisible();
    await expect(row.getByText("MANAGEMENT", { exact: true })).toBeVisible();
    // The linked staff profile survives the role change instead of being
    // recreated or discarded.
    await expect(row.getByText(department)).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("management cannot reach the staff account controls", async ({ page }) => {
    await login(page, USERS.management);
    await page.goto(app("/app/accounts"));
    await expect(page.getByText("Administrator access required")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create staff account" }),
    ).toHaveCount(0);
  });
});
