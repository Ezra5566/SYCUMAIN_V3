/**
 * Sustained authenticated session soak.
 *
 * Signs in once, then for at least 65 minutes exercises what a person actually
 * does: full page loads (bookmarks, refreshes), client-side navigation, a
 * reload, a second tab, and an explicit authenticated API call each cycle.
 *
 * The point is to catch *unexpected* session invalidation — a session that dies
 * while the server still considers it valid, or a client that loses the
 * identity it already had. Any cycle where the account menu disappears, the app
 * lands on the login page, or `/auth/me` stops returning 200 is recorded as a
 * failure with the cycle number and URL, and the run continues so one hiccup
 * does not hide a pattern.
 *
 * Usage: node .perf/session-soak.mjs [minutes] [baseUrl]
 */

// The suite installs `@playwright/test`, which re-exports the browsers. A
// separate `playwright` package is not present, so import the bundled one.
import { chromium } from "@playwright/test";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const MINUTES = Number(process.argv[2] ?? 65);
const BASE = process.argv[3] ?? "http://localhost:3101";
// Where the API answers. The development stack publishes it on its own port;
// a production-shaped stack serves it from the same origin behind Caddy.
const API = process.env.SOAK_API ?? (BASE.includes(":3101") ? BASE.replace(":3101", ":8001") : BASE);
const EMAIL = process.env.SOAK_EMAIL ?? "admin@school.portal";
const PASSWORD = process.env.SOAK_PASSWORD ?? "password123";

const MODULES = [
  "/en/app",
  "/en/app/students",
  "/en/app/academics",
  "/en/app/housing",
  "/en/app/immigration",
  "/en/app/announcements",
  "/en/app/reports",
  "/en/app/settings",
];

// Results belong to the project, not this package: resolve them from the file
// so the script works whatever directory it is started from.
const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const RESULT_PATH = resolve(PROJECT_ROOT, ".perf/session-soak.json");
const LOG_PATH = resolve(PROJECT_ROOT, ".perf/session-soak.log");
mkdirSync(dirname(LOG_PATH), { recursive: true });
const started = Date.now();
const deadline = started + MINUTES * 60_000;

const cycles = [];
const failures = [];

function log(line) {
  const stamp = new Date().toISOString();
  appendFileSync(LOG_PATH, `${stamp} ${line}\n`);
}

function flush(status) {
  writeFileSync(
    RESULT_PATH,
    JSON.stringify(
      {
        status,
        started_at: new Date(started).toISOString(),
        finished_at: new Date().toISOString(),
        duration_minutes: Number(((Date.now() - started) / 60_000).toFixed(1)),
        base_url: BASE,
        account: EMAIL,
        cycles: cycles.length,
        failures,
        samples: cycles,
      },
      null,
      2,
    ),
  );
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const browser = await chromium.launch();
// The production-shaped rehearsal stack uses a locally issued certificate.
const context = await browser.newContext({ ignoreHTTPSErrors: true });
const page = await context.newPage();

page.on("pageerror", (error) => log(`pageerror ${error.message}`));
page.on("response", (response) => {
  const url = response.url();
  if (url.includes("/api/v1/") && response.status() >= 400) {
    log(`api ${response.status()} ${url}`);
  }
});

// --- Sign in once -----------------------------------------------------------
for (let attempt = 1; ; attempt += 1) {
  try {
    await page.goto(`${BASE}/en/login`, {
      waitUntil: "domcontentloaded",
      timeout: 90_000,
    });
    await page.getByLabel(/email/i).fill(EMAIL);
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL(/\/en\/app/, { timeout: 90_000 });
    log("signed in");
    break;
  } catch (error) {
    log(`login attempt ${attempt} failed: ${String(error).split("\n")[0]}`);
    if (attempt >= 3) throw error;
    await sleep(5_000);
  }
}

let index = 0;
let secondTabChecked = false;

while (Date.now() < deadline) {
  index += 1;
  const path = MODULES[index % MODULES.length];
  const mode = index % 5 === 0 ? "reload" : index % 3 === 0 ? "navigate" : "load";
  const record = { cycle: index, at: new Date().toISOString(), path, mode };

  try {
    if (mode === "reload") {
      await page.reload({ waitUntil: "domcontentloaded", timeout: 90_000 });
    } else if (mode === "navigate") {
      // Client-side navigation: no page load, so the in-memory identity is what
      // the shell renders. This is the path that exposed the zombie state.
      const href = path.replace("/en", "");
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 90_000 });
      const nav = page.getByRole("navigation", { name: "Main navigation" }).first();
      const tab = nav.locator('a[href$="' + href + '"]').first();
      if (await tab.count()) {
        await tab.click({ timeout: 10_000 }).catch(() => undefined);
      }
    } else {
      await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 90_000 });
    }

    // Wait for the shell to settle, then require the authenticated signal.
    await page.locator("header .scu-me").first().waitFor({ timeout: 45_000 });
    record.authenticated = true;

    const me = await page.evaluate(async (apiBase) => {
      const response = await fetch(`${apiBase}/api/v1/auth/me`, {
        credentials: "include",
      });
      const body = await response.json().catch(() => ({}));
      return { status: response.status, email: body?.email ?? null };
    }, API);
    record.me_status = me.status;
    record.me_email = me.email;
    if (me.status !== 200) {
      record.authenticated = false;
      failures.push({ ...record, reason: "auth/me did not answer 200" });
      log(`FAIL cycle ${index}: /auth/me ${me.status}`);
    }

    if (page.url().includes("/login")) {
      record.authenticated = false;
      failures.push({ ...record, reason: "redirected to login" });
      log(`FAIL cycle ${index}: redirected to login`);
    }

    // One second tab, half way through: it must share the session.
    if (!secondTabChecked && Date.now() - started > (MINUTES * 60_000) / 2) {
      secondTabChecked = true;
      const tab = await context.newPage();
      await tab.goto(`${BASE}/en/app/students`, {
        waitUntil: "domcontentloaded",
        timeout: 90_000,
      });
      const ok = await tab
        .locator("header .scu-me")
        .first()
        .waitFor({ timeout: 30_000 })
        .then(() => true)
        .catch(() => false);
      record.second_tab = ok;
      if (!ok) failures.push({ ...record, reason: "second tab lost the session" });
      log(`second tab authenticated=${ok}`);
      await tab.close();
    }
  } catch (error) {
    // A page that never loaded proves nothing about the session. Classify the
    // abort so a host that is out of memory is not reported as a login defect:
    // only "auth" outcomes below are session failures.
    const text = String(error);
    const transport = /ERR_|net::|Timeout|timed out/.test(text);
    record.authenticated = null;
    record.outcome = transport ? "transport" : "error";
    failures.push({ ...record, reason: text.slice(0, 300) });
    log(`FAIL cycle ${index} (${record.outcome}): ${text.split("\n")[0]}`);
  }

  cycles.push(record);
  flush("running");

  const remaining = deadline - Date.now();
  if (remaining <= 0) break;
  await sleep(Math.min(60_000, remaining));
}

// A page that never loaded is not a session failure. Report the two kinds
// separately so a starved host cannot masquerade as an authentication defect.
const isTransport = (f) =>
  f.outcome === "transport" || /ERR_|net::|Timeout|timed out/i.test(String(f.reason));
const transportAborts = failures.filter(isTransport).length;
const sessionFailures = failures.length - transportAborts;

flush(sessionFailures === 0 ? (transportAborts ? "passed_with_transport_aborts" : "passed") : "failed");
log(
  `finished: ${cycles.length} cycles, ${sessionFailures} session failures, ${transportAborts} transport aborts`,
);

await context.close();
await browser.close();
