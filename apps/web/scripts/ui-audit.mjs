/**
 * Responsive + appearance audit.
 *
 * Signs in with the seeded demo account, then measures every guarded route at
 * five viewports: page overflow, header tool position, dock visibility, and
 * table containment. Finally exercises the accent picker and checks that it
 * re-themes without navigating and survives a reload.
 *
 * Run with the dev server on :3101:  node scripts/ui-audit.mjs
 */
import { chromium } from "@playwright/test";

const BASE = process.env.AUDIT_BASE ?? "http://localhost:3101";
const ROUTES = [
  "/en/app",
  "/en/app/students",
  "/en/app/housing",
  "/en/app/immigration",
  "/en/app/settings",
  "/en/app/examinations",
  "/ar/app",
];
const SIZES = [
  [390, 844],
  [768, 1024],
  [1024, 768],
  [1440, 900],
  [1920, 1080],
];

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

const failures = [];

async function login() {
  await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle" });
  // The form posts natively before hydration; wait for React to own onsubmit.
  await page.waitForTimeout(1200);
  await page.fill("#email", process.env.AUDIT_EMAIL ?? "admin@school.portal");
  await page.fill("#password", process.env.AUDIT_PASSWORD ?? "password123");
  await page.waitForTimeout(200);
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30000 });
  } catch (error) {
    const alert = await page.locator('[role="alert"]').allInnerTexts().catch(() => []);
    throw new Error(`login did not leave /login: ${alert.join(" | ")}`);
  }
  await page.waitForTimeout(800);
}

await login();

// The sign-in screen probes /auth/me before a session exists and logs one 401;
// only errors from the authenticated audit below are interesting.
consoleErrors.length = 0;

const rows = [];
for (const route of ROUTES) {
  for (const [width, height] of SIZES) {
    await page.setViewportSize({ width, height });
    await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
    // Dev-server route compilation can take seconds on a cold route; measure the
    // shell that is actually on screen, never a blank in-progress page.
    await page.waitForSelector(".scu-tools", { timeout: 45000 });
    await page.waitForTimeout(250);
    const metrics = await page.evaluate(() => {
      const doc = document.documentElement;
      const tools = document.querySelector(".scu-tools");
      const dock = document.querySelector(".scu-dock");
      const table = document.querySelector(".motion-table");
      const toolsRect = tools?.getBoundingClientRect();
      return {
        path: location.pathname,
        overflow: doc.scrollWidth - doc.clientWidth,
        toolsRight: toolsRect ? Math.round(toolsRect.right) : null,
        toolsWidth: toolsRect ? Math.round(toolsRect.width) : null,
        dock: dock ? getComputedStyle(dock).display : "absent",
        tableOverflow: table ? table.scrollWidth - table.clientWidth : null,
        tabs: document.querySelectorAll(".scu-tab").length,
        moreTrigger: Boolean(document.querySelector('[aria-label][aria-haspopup="menu"], .scu-tabs button[aria-label]')),
        railScrollable: (() => {
          const viewport = document.querySelector(".scu-tabs__viewport");
          return viewport ? viewport.scrollWidth > viewport.clientWidth + 1 : false;
        })(),
      };
    });
    rows.push({ route, width, ...metrics });
    if (metrics.overflow > 0) failures.push(`${route}@${width}: overflow ${metrics.overflow}px`);
    if (metrics.toolsRight === null) failures.push(`${route}@${width}: no header tools`);
    else if (metrics.toolsRight > width + 1) failures.push(`${route}@${width}: tools clipped at ${metrics.toolsRight}px`);
  }
}

// Accent picker: switching re-themes in place and persists across reload.
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE}/en/app/settings`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('input[value="violet"]', { timeout: 45000 });
await page.waitForTimeout(300);
const before = await page.evaluate(() => ({
  primary: getComputedStyle(document.documentElement).getPropertyValue("--primary").trim(),
  accent: document.documentElement.dataset.accent,
  path: location.pathname,
}));
await page.locator('label:has(input[value="violet"])').first().click();
await page.waitForTimeout(250);
const after = await page.evaluate(() => ({
  primary: getComputedStyle(document.documentElement).getPropertyValue("--primary").trim(),
  accent: document.documentElement.dataset.accent,
  path: location.pathname,
  stored: localStorage.getItem("scu-accent"),
}));
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(400);
const persisted = await page.evaluate(() => ({
  accent: document.documentElement.dataset.accent,
  primary: getComputedStyle(document.documentElement).getPropertyValue("--primary").trim(),
}));
// Restore the default so the audit does not change the developer's session.
await page.locator('label:has(input[value="institution"])').first().click();
await page.waitForTimeout(150);

const accent = {
  before,
  after,
  persisted,
  changed: before.primary !== after.primary && before.accent !== after.accent,
  stayedOnRoute: before.path === after.path,
  persistedOk: persisted.accent === "violet",
};
if (!accent.changed) failures.push("accent: --primary did not change");
if (!accent.stayedOnRoute) failures.push("accent: navigation occurred on switch");
if (!accent.persistedOk) failures.push("accent: choice did not survive reload");

// Mobile dialog containment.
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE}/en/app/students`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('table, [role="dialog"], h1', { timeout: 45000 });
await page.waitForTimeout(500);
let dialog = null;
const trigger = page.getByRole("button", { name: /new student|add student|create student/i }).first();
if (await trigger.count()) {
  await trigger.click();
  await page.waitForTimeout(400);
  dialog = await page.evaluate(() => {
    const node = document.querySelector('[role="dialog"]');
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    return { width: Math.round(rect.width), left: Math.round(rect.left), right: Math.round(rect.right) };
  });
  await page.keyboard.press("Escape");
  if (dialog && (dialog.width > 390 || dialog.right > 391)) {
    failures.push(`dialog@390 too wide: ${JSON.stringify(dialog)}`);
  }
}

// Reference captures for the handover: narrow dashboard and the accent picker.
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE}/en/app`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".scu-tools", { timeout: 45000 });
await page.waitForTimeout(600);
await page.screenshot({ path: new URL("../../../../solvik-mobile.png", import.meta.url).pathname });

await page.setViewportSize({ width: 1200, height: 1000 });
await page.goto(`${BASE}/en/app/settings`, { waitUntil: "domcontentloaded" });
await page.waitForSelector('input[name="accent"]', { timeout: 45000 });
await page.waitForTimeout(500);
await page.screenshot({ path: new URL("../../../../solvik-settings.png", import.meta.url).pathname });

console.log(JSON.stringify({ rows, accent, dialog, failures, consoleErrors: consoleErrors.slice(0, 8) }, null, 1));
await browser.close();
process.exit(failures.length > 0 ? 1 : 0);
