/**
 * Focused overflow probe: lists the elements pushing past the viewport on one
 * route at one width. Usage: node scripts/ui-probe.mjs /en/app/settings 390
 */
import { chromium } from "@playwright/test";

const BASE = process.env.AUDIT_BASE ?? "http://localhost:3101";
const route = process.argv[2] ?? "/en/app/settings";
const width = Number(process.argv[3] ?? 390);
const height = Number(process.argv[4] ?? 844);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width, height } });
const page = await context.newPage();

await page.goto(`${BASE}/en/login`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
await page.fill("#email", "admin@school.portal");
await page.fill("#password", "password123");
await page.click('button[type="submit"]');
await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30000 });

await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".scu-tools", { timeout: 45000 });
await page.waitForTimeout(700);

const result = await page.evaluate(() => {
  const viewport = window.innerWidth;
  const offenders = [...document.querySelectorAll("body *")]
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.right > viewport + 1 && style.position !== "fixed";
    })
    .slice(0, 12)
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        tag: element.tagName,
        cls: String(element.className ?? "").slice(0, 80),
        width: Math.round(rect.width),
        right: Math.round(rect.right),
        text: (element.textContent ?? "").trim().slice(0, 50),
      };
    });
  return {
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    offenders,
  };
});

console.log(JSON.stringify(result, null, 1));
await browser.close();
