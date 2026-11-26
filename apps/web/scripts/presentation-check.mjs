/**
 * Presentation interface check.
 *
 * Walks the modules a presenter opens, at desktop, tablet and phone widths,
 * plus the Arabic (RTL) interface, and records:
 *
 *   - horizontal page overflow (the layout failure that makes a page unusable);
 *   - a blank or near-blank render;
 *   - a missing page heading;
 *   - browser console errors and 5xx responses;
 *   - screenshots for visual review.
 *
 * It signs in once per role and resizes the same page, so it does not spend the
 * API's sign-in allowance testing three viewports.
 *
 * Usage (credentials come from scripts/demo_accounts.py):
 *   node scripts/presentation-check.mjs
 */

import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const CREDENTIALS = resolve(PROJECT_ROOT, ".demo-credentials.json");
const SHOTS = resolve(PROJECT_ROOT, ".perf/screens");
const RESULT = resolve(PROJECT_ROOT, ".perf/presentation-check.json");
const BASE = process.env.DEMO_BASE_URL ?? "http://localhost:3101";

mkdirSync(SHOTS, { recursive: true });

const accounts = Object.fromEntries(
  JSON.parse(readFileSync(CREDENTIALS, "utf8")).accounts.map((a) => [a.role, a]),
);

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 834, height: 1112 },
  { name: "mobile", width: 390, height: 844 },
];

const PAGES = [
  "/en/app",
  "/en/app/students",
  "/en/app/academics",
  "/en/app/housing",
  "/en/app/immigration",
  "/en/app/settings",
];

const NOISE = [
  /ERR_ABORTED/i,
  /NS_BINDING_ABORTED/i,
  /_rsc=/,
  /access control checks/i, // cancelled WebKit/Next prefetch, see smoke.spec
  /Download the React DevTools/i,
];

function isNoise(text) {
  return NOISE.some((pattern) => pattern.test(text));
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: VIEWPORTS[0] });
const page = await context.newPage();

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() !== "error") return;
  const text = message.text();
  if (!isNoise(text)) consoleErrors.push(text.slice(0, 300));
});
page.on("pageerror", (error) => {
  if (!isNoise(error.message)) consoleErrors.push(`pageerror: ${error.message}`.slice(0, 300));
});
page.on("response", (response) => {
  if (response.status() >= 500) {
    consoleErrors.push(`http ${response.status()} ${response.url()}`.slice(0, 300));
  }
});

async function login(role) {
  const account = accounts[role];

  // The form is `method="post"` before hydration (so a pre-hydration submit
  // cannot put a password in the URL). Clicking before React attaches would
  // therefore reload the login page instead of signing in, so wait for the
  // first compile to settle and retry once if that happened.
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

async function measure(path, label) {
  const errorsBefore = consoleErrors.length;
  await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 90_000 });
  await page.locator("main").first().waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1200); // let the first API render settle

  const metrics = await page.evaluate(() => {
    const root = document.documentElement;
    const text = (document.querySelector("main")?.innerText ?? "").trim();
    return {
      dir: root.getAttribute("dir"),
      overflowPx: Math.max(0, root.scrollWidth - window.innerWidth),
      textLength: text.length,
      heading: document.querySelector("main h1")?.textContent?.trim() ?? null,
    };
  });

  const row = {
    label,
    path,
    ...metrics,
    consoleErrors: consoleErrors.slice(errorsBefore),
  };
  row.ok =
    row.overflowPx <= 2 && row.textLength > 80 && Boolean(row.heading) && row.consoleErrors.length === 0;
  return row;
}

const results = [];

await login("ADMIN");

for (const viewport of VIEWPORTS) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  for (const path of PAGES) {
    results.push(await measure(path, `${viewport.name} ${path}`));
  }
  for (const path of ["/en/app", "/en/app/students"]) {
    await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
    await page.locator("main").first().waitFor();
    await page.waitForTimeout(800);
    const name = path.replace(/\//g, "_") || "dashboard";
    await page.screenshot({
      path: resolve(SHOTS, `${viewport.name}${name}.png`),
      fullPage: false,
    });
  }
}

// Arabic: a genuine RTL document, not a mirrored skin.
await page.setViewportSize({ width: 1440, height: 900 });
results.push(await measure("/ar/app", "desktop /ar/app"));
results.push(await measure("/ar/app/students", "desktop /ar/app/students"));
await page.goto(`${BASE}/ar/app`, { waitUntil: "domcontentloaded" });
await page.locator("main").first().waitFor();
await page.waitForTimeout(800);
await page.screenshot({ path: resolve(SHOTS, "desktop_arabic_dashboard.png"), fullPage: false });

// Student self-service, on a phone.
await context.clearCookies();
await login("STUDENT");
await page.setViewportSize({ width: 390, height: 844 });
results.push(await measure("/en/app", "mobile student /en/app"));
await page.screenshot({ path: resolve(SHOTS, "mobile_student_dashboard.png"), fullPage: false });

const failures = results.filter((row) => !row.ok);

writeFileSync(RESULT, JSON.stringify({ base: BASE, results, failures }, null, 2));

for (const row of results) {
  console.log(
    `${row.ok ? "ok  " : "FAIL"} ${row.label.padEnd(38)} dir=${row.dir} overflow=${row.overflowPx}px chars=${row.textLength} heading=${JSON.stringify(row.heading)} errors=${row.consoleErrors.length}`,
  );
}
console.log(`\n${results.length - failures.length}/${results.length} passed; screenshots in ${SHOTS}`);

await context.close();
await browser.close();
process.exit(failures.length === 0 ? 0 : 1);
