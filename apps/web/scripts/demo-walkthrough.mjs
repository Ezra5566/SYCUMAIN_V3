/**
 * Four-role presentation walkthrough.
 *
 * The rehearsal a presenter actually performs: sign in through the real form as
 * each role, open that role's pages, and refresh to prove the screen does not
 * depend on in-memory state from the previous step.
 *
 * Credentials are read from `.demo-credentials.json` (written by
 * `scripts/demo_accounts.py`, mode 0600, git-ignored).
 *
 *   node scripts/demo-walkthrough.mjs
 */

import { chromium } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const CREDENTIALS = resolve(PROJECT_ROOT, ".demo-credentials.json");
const RESULT = resolve(PROJECT_ROOT, ".perf/demo-walkthrough.json");
const BASE = process.env.DEMO_BASE_URL ?? "http://localhost:3101";

const accounts = Object.fromEntries(
  JSON.parse(readFileSync(CREDENTIALS, "utf8")).accounts.map((a) => [a.role, a]),
);

const TOUR = {
  ADMIN: [
    "/en/app",
    "/en/app/students",
    "/en/app/academics",
    "/en/app/academics/calendar",
    "/en/app/housing",
    "/en/app/immigration",
    "/en/app/announcements",
    "/en/app/reports",
    "/en/app/audit",
    "/en/app/settings",
  ],
  MANAGEMENT: [
    "/en/app",
    "/en/app/students",
    "/en/app/academics",
    "/en/app/academics/calendar",
    "/en/app/housing",
    "/en/app/reports",
  ],
  TEACHER: ["/en/app", "/en/app/students", "/en/app/academics", "/en/app/attendance"],
  STUDENT: ["/en/app", "/en/app/profile", "/en/app/announcements", "/en/app/settings"],
};

const browser = await chromium.launch();
const results = [];
const consoleErrors = [];

async function login(page, account) {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle", timeout: 90_000 });
    await page.getByLabel(/email/i).fill(account.email);
    await page.getByLabel(/password/i).fill(account.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    try {
      await page.waitForURL(/\/en\/app/, { timeout: 30_000 });
      return;
    } catch (error) {
      if (attempt === 2) throw error;
    }
  }
}

for (const [role, paths] of Object.entries(TOUR)) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`${role}: ${message.text().slice(0, 200)}`);
  });

  await login(page, accounts[role]);

  for (const path of paths) {
    const before = consoleErrors.length;
    await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForTimeout(900);

    // A refresh is the step a presenter does while talking; the screen must
    // come back rather than fall to the login page.
    await page.reload({ waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.locator("main").first().waitFor({ timeout: 45_000 });
    await page.waitForTimeout(600);

    const state = await page.evaluate(() => ({
      url: location.pathname,
      heading: document.querySelector("main h1")?.textContent?.trim() ?? null,
      chars: (document.querySelector("main")?.innerText ?? "").trim().length,
    }));

    results.push({
      role,
      path,
      ...state,
      authenticated: !state.url.includes("/login"),
      consoleErrors: consoleErrors.slice(before),
      ok:
        !state.url.includes("/login") &&
        state.chars > 80 &&
        Boolean(state.heading) &&
        consoleErrors.length === before,
    });
  }

  await page.screenshot({
    path: resolve(PROJECT_ROOT, `.perf/screens/role-${role.toLowerCase()}.png`),
    fullPage: false,
  });
  await context.close();
}

const failures = results.filter((row) => !row.ok);
writeFileSync(RESULT, JSON.stringify({ base: BASE, results, failures }, null, 2));

for (const row of results) {
  console.log(
    `${row.ok ? "ok  " : "FAIL"} ${row.role.padEnd(10)} ${row.path.padEnd(22)} heading=${JSON.stringify(row.heading)} chars=${row.chars} errors=${row.consoleErrors.length}`,
  );
}
console.log(`\n${results.length - failures.length}/${results.length} passed`);

await browser.close();
process.exit(failures.length === 0 ? 0 : 1);
