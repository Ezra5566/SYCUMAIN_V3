import { expect, test, type Page } from "@playwright/test";

import { USERS } from "./accounts";

/**
 * Visual capture of the stabilized UI.
 *
 * Run with:  pnpm screenshots
 * Output:    apps/web/screenshots/*.png
 *
 * These are review artefacts, not assertions — the only hard assertion is that
 * each page rendered real data (no error state was shown).
 *
 * Requires a running stack (see playwright.config.ts).
 */
const OUT = "screenshots";

async function signIn(page: Page, user: { email: string; password: string }) {
  await page.goto("/en/login");
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/app/, { timeout: 20_000 });
}

/** Screenshot a route and fail loudly if the page rendered an error state. */
async function shoot(page: Page, url: string, name: string) {
  await page.goto(url);
  await page.waitForTimeout(1200);
  await expect(page.getByText(/something went wrong/i)).toHaveCount(0);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}

/** Pull the first in-app link whose href matches `pattern`. */
async function firstHref(page: Page, pattern: RegExp): Promise<string | null> {
  const hrefs = await page.locator("a[href]").evaluateAll((els) =>
    els.map((el) => el.getAttribute("href") || ""),
  );
  return hrefs.find((h) => pattern.test(h)) ?? null;
}

test.describe("visual review", () => {
  test("admin: dashboard, students, profile, housing, immigration, academics", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, USERS.admin);

    await shoot(page, "/en/app", "01-dashboard");

    await page.goto("/en/app/students");
    await page.waitForTimeout(1000);
    const studentHref = await firstHref(page, /^\/en\/app\/students\/[0-9a-f-]{8,}/i);
    await shoot(page, "/en/app/students", "02-student-directory");

    if (studentHref) {
      await shoot(page, studentHref, "03-student-profile");

      // The profile tabs are client state, so they must be clicked.
      await page.goto(studentHref);
      await page.waitForTimeout(1000);
      for (const tab of ["Academic", "Immigration", "Housing"]) {
        await page.getByRole("tab", { name: tab, exact: true }).click();
        await page.waitForTimeout(900);
        await page.screenshot({
          path: `${OUT}/03b-profile-${tab.toLowerCase()}-tab.png`,
          fullPage: true,
        });
      }
    }

    await page.goto("/en/app/housing");
    await page.waitForTimeout(1000);
    const buildingHref = await firstHref(page, /^\/en\/app\/housing\/[0-9a-f-]{8,}$/i);
    await shoot(page, "/en/app/housing", "04-housing-buildings");

    if (buildingHref) {
      await shoot(page, buildingHref, "05-housing-building");

      await page.goto(buildingHref);
      await page.waitForTimeout(1000);
      const floorHref = await firstHref(
        page,
        /^\/en\/app\/housing\/[0-9a-f-]{8,}\/[0-9a-f-]{8,}$/i,
      );

      if (floorHref) {
        await shoot(page, floorHref, "06-housing-floor");

        await page.goto(floorHref);
        await page.waitForTimeout(1000);
        const roomHref = await firstHref(
          page,
          /^\/en\/app\/housing\/[0-9a-f-]{8,}\/[0-9a-f-]{8,}\/[0-9a-f-]{8,}$/i,
        );
        if (roomHref) await shoot(page, roomHref, "07-housing-room");
      }
    }

    await shoot(page, "/en/app/immigration", "08-immigration");
    await shoot(page, "/en/app/academics", "09-academics");
  });

  test("admin: stage 7 platform modules", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, USERS.admin);

    await shoot(page, "/en/app/announcements", "13-announcements");

    // A composed dialog is the only place the multilingual form appears.
    await page.goto("/en/app/announcements");
    await page.waitForTimeout(900);
    await page.getByRole("button", { name: /new announcement/i }).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/14-announcement-compose.png`, fullPage: true });
    await page.keyboard.press("Escape");

    await shoot(page, "/en/app/support", "15-support-list");

    await page.goto("/en/app/support");
    await page.waitForTimeout(1000);
    const ticketHref = await firstHref(page, /^\/en\/app\/support\/[0-9a-f-]{8,}$/i);
    if (ticketHref) await shoot(page, ticketHref, "16-support-ticket");

    await shoot(page, "/en/app/notifications", "17-notifications");
    await shoot(page, "/en/app/documents", "18-documents");
    await shoot(page, "/en/app/reports", "19-reports");
    await shoot(page, "/en/app/audit", "20-audit-log");
  });

  test("arabic RTL: platform modules", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, USERS.admin);
    for (const [url, name] of [
      ["/ar/app/announcements", "21-ar-announcements"],
      ["/ar/app/support", "22-ar-support"],
      ["/ar/app/reports", "23-ar-reports"],
    ] as const) {
      await shoot(page, url, name);
    }
  });

  test("student: role-scoped dashboard", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page, USERS.student);
    await shoot(page, "/en/app", "10-dashboard-student");
  });

  test("mobile: responsive layout", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, USERS.admin);
    await shoot(page, "/en/app/students", "11-mobile-directory");
    await shoot(page, "/en/app", "12-mobile-dashboard");
  });

  test("login page", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/en/login");
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}/00-login.png`, fullPage: true });
  });
});
