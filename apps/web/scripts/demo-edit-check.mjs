/**
 * Proves the demonstration account can still edit and save its own details,
 * and that the saved value survives a reload (i.e. reached the database).
 *
 *   node scripts/demo-edit-check.mjs
 */

import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const BASE = process.env.DEMO_BASE_URL ?? "http://localhost:3101";

const accounts = JSON.parse(readFileSync(resolve(PROJECT_ROOT, ".demo-credentials.json"), "utf8"))
  .accounts;
const student = accounts.find((account) => account.role === "STUDENT");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const phone = `+86-138-${Date.now().toString().slice(-8)}`;

await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle", timeout: 90_000 });
await page.getByLabel(/email/i).fill(student.email);
await page.getByLabel(/password/i).fill(student.password);
await page.getByRole("button", { name: /sign in/i }).click();
await page.waitForURL(/\/en\/app/, { timeout: 30_000 });

await page.goto(`${BASE}/en/app/profile`, { waitUntil: "domcontentloaded" });
await page.getByRole("button", { name: /edit my details/i }).click();
const dialog = page.getByRole("dialog");
await dialog.getByLabel(/^phone/i).fill(phone);
await dialog.getByRole("button", { name: /^save$/i }).click();

await page.reload({ waitUntil: "domcontentloaded" });
await page.getByText(phone).first().waitFor({ timeout: 25_000 });

console.log(`ok  saved and persisted after reload: ${phone} (${student.email})`);
await browser.close();
