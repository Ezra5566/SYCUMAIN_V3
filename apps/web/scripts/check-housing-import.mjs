/**
 * Browser check for the housing allocation importer.
 *
 * Preview only: it exercises the real dialog, real upload and real API, and
 * deliberately never confirms the import, so it is safe to run against a
 * demonstration database.
 */
import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const BASE = process.env.E2E_BASE_URL || "http://localhost:3101";
const OUT = process.env.OUT || "/tmp";

const csv = [
  "student_id,building,floor,room,bed,start_date",
  "STU-123,No Such Hall,1,101,1,2026-09-01",
  "STU-404,Building 18,1,104,3,2026-09-01",
  "STU-123,Building 18,1,104,3,32/13/2026",
].join("\n");

const file = join(OUT, "synthetic-housing.csv");
writeFileSync(file, csv + "\n");

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle" });
await page.fill('input[type="email"], input[name="email"]', "admin@school.portal");
await page.fill('input[type="password"], input[name="password"]', "password123");
await page.click('button[type="submit"]');
await page.waitForURL(/\/en\/app($|\?)/, { timeout: 20000 });

await page.goto(`${BASE}/en/app/housing`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /import allocations/i }).click();
await page.setInputFiles("#housing-import-file", file);
await page.getByRole("button", { name: /^preview$/i }).click();
await page.getByRole("status").waitFor({ timeout: 20000 });

const summary = await page.getByRole("status").innerText();
const rows = await page.locator("table tbody tr").count();
const tableText = await page.locator("table tbody").innerText();
const applyDisabled = await page
  .getByRole("button", { name: /confirm import/i })
  .isDisabled();

await page.screenshot({ path: join(OUT, "housing-import-preview.png") });

// Arabic RTL sanity: the dialog must mirror, not clip.
await page.goto(`${BASE}/ar/app/housing`, { waitUntil: "networkidle" });
const dir = await page.locator("html").getAttribute("dir");
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);

await browser.close();

console.log(
  JSON.stringify(
    { summary, rows, applyDisabled, dir, overflow, errors, tableText: tableText.slice(0, 400) },
    null,
    2,
  ),
);
if (errors.length || overflow > 0) process.exit(1);
