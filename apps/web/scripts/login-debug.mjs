/**
 * Reproduces a UI sign-in and prints what actually happened: page URL, visible
 * error text, console messages and every auth-related network exchange.
 *
 *   node scripts/login-debug.mjs [baseUrl] [email]
 */

import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const BASE = process.argv[2] ?? "http://localhost:3101";
const EMAIL = process.argv[3] ?? "admin@school.portal";

const accounts = JSON.parse(readFileSync(resolve(PROJECT_ROOT, ".demo-credentials.json"), "utf8"))
  .accounts;
const account = accounts.find((a) => a.email === EMAIL) ?? accounts[0];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

page.on("console", (m) => console.log(`console.${m.type()}: ${m.text().slice(0, 200)}`));
page.on("pageerror", (e) => console.log(`pageerror: ${String(e).slice(0, 200)}`));
page.on("response", async (r) => {
  const url = r.url();
  if (!/auth|login|me|session/i.test(url)) return;
  let body = "";
  try {
    body = (await r.text()).slice(0, 200);
  } catch {
    body = "<unreadable>";
  }
  console.log(`response ${r.status()} ${r.request().method()} ${url} :: ${body.replace(/\s+/g, " ")}`);
});

console.log(`base=${BASE} email=${account.email}`);
await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle", timeout: 90_000 });
console.log(`loaded: ${page.url()}`);

await page.getByLabel(/email/i).fill(account.email);
await page.getByLabel(/password/i).fill(account.password);
await page.getByRole("button", { name: /sign in/i }).click();
await page.waitForTimeout(6000);

console.log(`after click: ${page.url()}`);
console.log(`cookies: ${JSON.stringify((await page.context().cookies()).map((c) => `${c.name}@${c.domain}`))}`);
const text = (await page.locator("body").innerText()).replace(/\n{2,}/g, "\n").slice(0, 900);
console.log("--- visible text ---");
console.log(text);

await page.screenshot({ path: resolve(PROJECT_ROOT, ".perf/screens/login-debug.png") });
await browser.close();
