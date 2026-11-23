/**
 * Browser certification run.
 *
 * Evidence, not a smoke test: it drives the real UI as each role and calls the
 * real API with the same cookies, because a hidden button is not an
 * authorization boundary.
 *
 * One session per account is reused deliberately. Repeated sign-ins trip the
 * login rate limiter, which is a control worth keeping; a test that defeats it
 * to run faster would be testing a different system.
 *
 *   node scripts/certify-e2e.mjs
 */
import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL || "http://localhost:3101";
const API = process.env.API_BASE_URL || "http://localhost:8001";

const ROUTES = [
  "/app",
  "/app/students",
  "/app/housing",
  "/app/immigration",
  "/app/academics",
  "/app/academics/calendar",
  "/app/attendance",
  "/app/examinations",
  "/app/admissions/verification",
  "/app/admissions/commencement",
  "/app/documents",
  "/app/announcements",
  "/app/support",
  "/app/reports",
  "/app/audit",
  "/app/accounts",
  "/app/notifications",
  "/app/profile",
  "/app/settings",
];

const LOCALES = ["en", "zh", "fr", "ru", "ar"];

const ROLES = {
  admin: "admin@school.portal",
  management: "management@school.portal",
  teacher: "teacher@school.portal",
  student: "student@school.portal",
};

const MUST_DENY = {
  student: ["/app/students", "/app/accounts", "/app/audit", "/app/reports"],
  teacher: ["/app/accounts", "/app/audit"],
};

const results = { routes: [], roles: [], api: [], locales: [], interactions: [] };
const failures = [];

function check(kind, name, ok, detail) {
  results[kind].push({ name, ok, detail });
  if (!ok) failures.push(`${kind}: ${name} — ${detail}`);
}

function isDenied(url) {
  return /\/forbidden|\/unauthorized|\/login/.test(url);
}

// Pages rendered for everyone but filled with a permission notice, or (profile)
// an empty state for staff without a student record.
const DENIAL_TEXT = [
  /do not have permission/i,
  /Administrator access required/i,
  /No student record/i,
  /Only an administrator/i,
];

// HTTP failures are asserted from real responses; the browser's generic
// "Failed to load resource" console line adds nothing and would double-count.
function isExpectedNoise(text) {
  return /Failed to load resource/.test(text);
}

// Expected negatives: the login page probing for a session that does not exist
// yet, and a staff account asking for a student record it does not have.
function isExpectedHttp(url, status) {
  return (
    (status === 401 && /\/auth\/me/.test(url)) ||
    (status === 404 && /\/students\/me/.test(url))
  );
}

const browser = await chromium.launch();
const sessions = new Map();

async function getSession(email) {
  if (sessions.has(email)) return sessions.get(email);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  await page.goto(`${BASE}/en/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', "password123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/en\/app($|\?)/, { timeout: 30000 });
  const session = { context, page };
  sessions.set(email, session);
  return session;
}

// --- 1. Every route as Admin ------------------------------------------------
{
  const { page } = await getSession(ROLES.admin);
  for (const route of ROUTES) {
    const errors = [];
    const badResponses = [];
    const onConsole = (msg) => {
      if (msg.type() === "error" && !isExpectedNoise(msg.text())) errors.push(msg.text());
    };
    const onResponse = (res) => {
      if (res.status() >= 400 && !isExpectedHttp(res.url(), res.status())) {
        badResponses.push(`${res.status()} ${res.url()}`);
      }
    };
    page.on("console", onConsole);
    page.on("response", onResponse);

    let status = "ok";
    try {
      const response = await page.goto(`${BASE}/en${route}`, {
        waitUntil: "networkidle",
        timeout: 45000,
      });
      status = String(response?.status() ?? 0);
    } catch (error) {
      status = `navigation failed: ${error.message}`;
    }
    await page.waitForTimeout(200);

    const url = page.url();
    const body = await page.locator("body").innerText().catch(() => "");
    const redirected = !url.includes(`/en${route}`);
    const blank = body.trim().length < 40;
    check(
      "routes",
      route,
      !redirected && !blank && errors.length === 0 && badResponses.length === 0,
      JSON.stringify({ status, url, redirected, blank, errors, badResponses }),
    );

    page.off("console", onConsole);
    page.off("response", onResponse);
  }
}

// --- 2. Role visibility across every route ----------------------------------
for (const [role, email] of Object.entries(ROLES)) {
  const { page } = await getSession(email);
  const seen = [];
  for (const route of ROUTES) {
    await page.goto(`${BASE}/en${route}`, { waitUntil: "networkidle" }).catch(() => {});
    const body = await page.locator("main, body").last().innerText().catch(() => "");
    const rows = await page.locator("table tbody tr").count();
    const notice = DENIAL_TEXT.some((pattern) => pattern.test(body));
    seen.push({ route, denied: isDenied(page.url()) || notice, rows, url: page.url() });
  }
  const wrong = [];
  for (const route of MUST_DENY[role] ?? []) {
    const entry = seen.find((item) => item.route === route);
    // Closed either by redirecting or by a notice with no records behind it.
    if (entry && !(entry.denied && entry.rows === 0)) wrong.push(route);
  }
  check(
    "roles",
    `${role} visibility`,
    wrong.length === 0,
    JSON.stringify({
      unexpectedlyAllowed: wrong,
      allowed: seen.filter((s) => !s.denied).map((s) => s.route),
    }),
  );
}

// --- 3. Direct API authorization, bypassing the UI ---------------------------
{
  const { context: adminContext } = await getSession(ROLES.admin);
  const adminRequest = adminContext.request;
  const list = await adminRequest.get(`${API}/api/v1/students/?page_size=2`);
  const students = (await list.json()).items ?? [];
  const other = students.find((s) => s.student_id !== "STU-001") ?? students[0];

  const student = (await getSession(ROLES.student)).context.request;
  const studentProbes = [
    ["GET students directory", "GET", "/api/v1/students/", [403]],
    ["GET audit log", "GET", "/api/v1/audit?page_size=5", [403]],
    ["GET another student record", "GET", `/api/v1/students/${other.id}`, [403, 404]],
    ["GET another student housing", "GET", `/api/v1/housing/students/${other.id}/housing`, [403, 404]],
    ["POST housing import", "POST", "/api/v1/housing/import/apply", [403, 422]],
    ["POST immigration import", "POST", "/api/v1/immigration/import/apply", [403, 422]],
    ["GET own profile", "GET", "/api/v1/students/me", [200]],
    ["GET notifications", "GET", "/api/v1/notifications/unread-count", [200]],
  ];
  for (const [name, method, path, expected] of studentProbes) {
    const response =
      method === "POST"
        ? await student.post(`${API}${path}`)
        : await student.get(`${API}${path}`);
    check(
      "api",
      `student ${name}`,
      expected.includes(response.status()),
      `${response.status()} (expected ${expected.join("/")})`,
    );
  }

  // A real mutation: change own phone, read it back, restore it.
  const me = await (await student.get(`${API}/api/v1/students/me`)).json();
  const original = me.phone ?? null;
  const marker = `+1 555 ${String(Date.now()).slice(-4)}`;
  const patch = await student.patch(`${API}/api/v1/students/${me.id}/self`, {
    data: { phone: marker },
  });
  const after = await (await student.get(`${API}/api/v1/students/me`)).json();
  const restored = await student.patch(`${API}/api/v1/students/${me.id}/self`, {
    data: { phone: original },
  });
  check(
    "api",
    "student self-update persists",
    patch.ok() && after.phone === marker && restored.ok(),
    JSON.stringify({ patch: patch.status(), stored: after.phone, restored: restored.status() }),
  );

  const teacher = (await getSession(ROLES.teacher)).context.request;
  for (const [name, method, path, expected] of [
    // Allowed by permission but scoped to the teacher's own rosters by the
    // service (covered by backend scope tests).
    ["students directory (scoped)", "GET", "/api/v1/students/?page_size=100", [200]],
    ["audit log", "GET", "/api/v1/audit?page_size=5", [403]],
    ["staff accounts", "GET", "/api/v1/users/?page_size=5", [403]],
    ["housing import", "POST", "/api/v1/housing/import/apply", [403, 422]],
  ]) {
    const response =
      method === "POST"
        ? await teacher.post(`${API}${path}`)
        : await teacher.get(`${API}${path}`);
    check(
      "api",
      `teacher ${name}`,
      expected.includes(response.status()),
      `${response.status()} (expected ${expected.join("/")})`,
    );
  }

  const management = (await getSession(ROLES.management)).context.request;
  for (const [name, method, path, expected] of [
    ["staff accounts (read)", "GET", "/api/v1/users/?page_size=5", [200]],
    ["student directory", "GET", "/api/v1/students/?page_size=5", [200]],
  ]) {
    const response = await management.get(`${API}${path}`);
    check(
      "api",
      `management ${name}`,
      expected.includes(response.status()),
      `${response.status()} (expected ${expected.join("/")})`,
    );
  }
  // Read-only is the boundary: Management may see accounts for student
  // administration, but cannot mint an administrator.
  const createAdmin = await management.post(`${API}/api/v1/users/`, {
    data: {
      email: `certify.denied.${Date.now()}@school.portal`,
      full_name: "Certification Probe",
      roles: ["ADMIN"],
    },
  });
  check(
    "api",
    "management cannot create an administrator",
    createAdmin.status() === 403,
    `${createAdmin.status()} (expected 403)`,
  );

  await adminContext.request.get(`${API}/api/v1/health`);
}

// --- 4. Five locales through the browser ------------------------------------
{
  const { page } = await getSession(ROLES.admin);
  for (const locale of LOCALES) {
    const visited = [];
    const errors = [];
    const onConsole = (msg) => {
      if (msg.type() === "error" && !isExpectedNoise(msg.text())) errors.push(msg.text());
    };
    page.on("console", onConsole);

    for (const route of ["/app", "/app/students", "/app/housing"]) {
      await page.goto(`${BASE}/${locale}${route}`, { waitUntil: "networkidle" }).catch(() => {});
      const dir = await page.locator("html").getAttribute("dir");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      const navText = await page.locator("nav").first().innerText().catch(() => "");
      visited.push({ route, dir, overflow, navText: navText.slice(0, 80) });
    }

    const expectedDir = locale === "ar" ? "rtl" : "ltr";
    const badDir = visited.filter((v) => v.dir !== expectedDir);
    const badOverflow = visited.filter((v) => v.overflow > 0);
    const englishNav =
      locale === "en"
        ? false
        : visited.some((v) => /Dashboard|Students|Housing/.test(v.navText));
    check(
      "locales",
      locale,
      badDir.length === 0 && badOverflow.length === 0 && !englishNav && errors.length === 0,
      JSON.stringify({ visited, badDir, badOverflow, englishNav, errors }),
    );
    page.off("console", onConsole);
  }
}

// --- 5. UI interactions: table, search, quick view, dialogs ------------------
{
  const { page } = await getSession(ROLES.admin);
  const notes = [];
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isExpectedNoise(msg.text())) errors.push(msg.text());
  });

  await page.goto(`${BASE}/en/app/students`, { waitUntil: "networkidle" });
  const rowsBefore = await page.locator("table tbody tr").count();
  notes.push(`rows before search: ${rowsBefore}`);

  const search = page.getByPlaceholder(/search/i).first();
  await search.fill("STU-001");
  await page.waitForTimeout(900);
  const rowsAfter = await page.locator("table tbody tr").count();
  notes.push(`rows after search: ${rowsAfter}`);

  const quickView = page.getByRole("button", { name: /quick view|view/i }).first();
  let peekOpened = false;
  if (await quickView.count()) {
    await quickView.click();
    peekOpened = await page
      .getByRole("dialog")
      .waitFor({ timeout: 5000 })
      .then(() => true)
      .catch(() => false);
    await page.keyboard.press("Escape");
  }
  notes.push(`quick view opened: ${peekOpened}`);

  await page.goto(`${BASE}/en/app/housing`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /import allocations/i }).click();
  const importOpened = await page
    .getByRole("dialog")
    .waitFor({ timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  await page.keyboard.press("Escape");

  await page.goto(`${BASE}/en/app/notifications`, { waitUntil: "networkidle" });
  const notificationsRendered = (await page.locator("body").innerText()).length > 100;

  check(
    "interactions",
    "table search, quick view and dialogs",
    rowsBefore > 0 &&
      rowsAfter > 0 &&
      peekOpened &&
      importOpened &&
      notificationsRendered &&
      errors.length === 0,
    JSON.stringify({ notes, importOpened, notificationsRendered, errors }),
  );
  page.off("console", errors.length ? () => {} : () => {});
}

for (const { context } of sessions.values()) await context.close();
await browser.close();

const summary = {
  checked: {
    routes: results.routes.length,
    roles: results.roles.length,
    api: results.api.length,
    locales: results.locales.length,
    interactions: results.interactions.length,
  },
  failures,
  results,
};
console.log(JSON.stringify(summary, null, 2));
if (failures.length > 0) process.exit(1);
