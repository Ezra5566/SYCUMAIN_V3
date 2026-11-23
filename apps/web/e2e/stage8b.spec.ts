import { expect, test, type Page } from "@playwright/test";

import { ADMIN, API_BASE, TEACHER } from "./accounts";

/**
 * Operational lifecycle browser tests (Stage 8B).
 *
 * These cover the workflows that a green unit suite cannot prove, because they
 * only exist as a chain of HTTP calls, redirects and cookie changes:
 *
 *   admin onboards a student -> one-time credential -> the student signs in
 *   -> sees only their own record -> edits their own details
 *
 * plus the account-security surface (password change, session revocation) and
 * the bulk administrative path.
 *
 * Runs against the real Docker stack; requires `docker compose up`.
 */

const LOCALE = "en";
const app = (path: string) => `/${LOCALE}${path}`;

let sequence = 0;

/**
 * Build a unique student identity for a single test.
 *
 * Identities must be unique per test, not per run: onboarding is idempotent on
 * the student number, so reusing one across tests would make every test after
 * the first fail with a conflict instead of exercising the flow.
 */
function newStudent() {
  sequence += 1;
  const stamp = `${Date.now().toString().slice(-7)}${sequence}`;
  return {
    number: `STU-E2E-${stamp}`,
    email: `e2e-student-${stamp}@example.com`,
    firstName: "E2E",
    lastName: `Onboard${stamp}`,
    password: `E2e-Onboard!${stamp}`,
  };
}

function trackPageHealth(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (err) => failures.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    if (req.failure()?.errorText?.includes("ERR_ABORTED")) return;
    failures.push(`requestfailed: ${req.method()} ${req.url()}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 500) failures.push(`http ${res.status()}: ${res.url()}`);
  });
  return failures;
}

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/app`), { timeout: 25_000 });
}

async function signOut(page: Page) {
  // `exact` matters: settings also renders a "Sign out other devices" button.
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(new RegExp(`/${LOCALE}/login`), { timeout: 25_000 });
}

/**
 * Onboard a student as admin and return the one-time temporary password.
 *
 * This is the flagship Stage 8B workflow: before it existed, the student record
 * could not be created at all, because a student needs a login account and
 * there was no way to create one.
 */
async function onboardStudent(
  page: Page,
): Promise<{ student: ReturnType<typeof newStudent>; password: string }> {
  const student = newStudent();

  await login(page, ADMIN);
  await page.goto(app("/app/students"));
  await page.getByRole("button", { name: /add student/i }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await dialog.getByLabel(/student number/i).fill(student.number);
  await dialog.getByLabel(/first name/i).fill(student.firstName);
  await dialog.getByLabel(/last name/i).fill(student.lastName);
  await dialog.getByLabel(/^email/i).fill(student.email);
  await dialog.getByRole("button", { name: /^create$/i }).click();

  // Phase two of the dialog: the credential, shown exactly once.
  const passwordField = page.getByTestId("temporary-password");
  await expect(passwordField).toBeVisible({ timeout: 25_000 });
  const password = (await passwordField.innerText()).trim();
  expect(password.length).toBeGreaterThanOrEqual(16);

  await page.getByRole("button", { name: /done/i }).click();
  return { student, password };
}

/**
 * Focus the directory on a single student.
 *
 * The directory is server-paginated, so the row is not guaranteed to be on the
 * first page; searching by the unique student number is the deterministic way
 * to reach it.
 *
 * The search box debounces, and applying a filter clears the current selection.
 * A test that selected a row before that request landed would have its
 * selection wiped when the dialog opened ("Apply a new status to 0 selected
 * students"). Waiting for the filtered response removes the race — it only
 * showed up on a fresh database, where the new student is already on page 1.
 */
async function findInDirectory(page: Page, studentNumber: string) {
  await page.goto(app("/app/students"));

  const filtered = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().includes("/api/v1/students") &&
      response.url().includes("search="),
  );
  await page.getByRole("searchbox", { name: "Search" }).fill(studentNumber);
  await filtered;

  const row = page.getByRole("row").filter({ hasText: studentNumber });
  await expect(row.first()).toBeVisible({ timeout: 25_000 });
  return row;
}

/**
 * Sign out and sign back in as the freshly onboarded student.
 *
 * A temporary password is single-use by design: the server refuses every API
 * except the password change until it is replaced (`403
 * PASSWORD_CHANGE_REQUIRED`). A test that wants to exercise student features
 * therefore has to do what the student does — choose a new password first.
 * Pass `completeChange: false` to observe the restricted state itself.
 */
async function signInAsStudent(
  page: Page,
  onboarded: { student: ReturnType<typeof newStudent>; password: string },
  { completeChange = true }: { completeChange?: boolean } = {},
) {
  await signOut(page);
  await login(page, {
    email: onboarded.student.email,
    password: onboarded.password,
  });

  if (!completeChange) return;

  // The guard routes a temporary-password session to settings.
  await page.goto(app("/app/settings"));
  await page.getByLabel(/current password/i).fill(onboarded.password);
  await page.getByLabel(/^new password$/i).fill(onboarded.student.password);
  await page.getByLabel(/confirm new password/i).fill(onboarded.student.password);
  await page.getByRole("button", { name: /change password/i }).click();
  await expect(page.getByText(/password was changed/i)).toBeVisible({
    timeout: 25_000,
  });

  await page.goto(app("/app"));
  await expect(page).toHaveURL(new RegExp(`/${LOCALE}/app$`));
}

test.describe("student account lifecycle", () => {
  test("admin onboards a student who can then sign in with the one-time password", async ({
    page,
  }) => {
    const failures = trackPageHealth(page);
    const onboarded = await onboardStudent(page);

    // The new student appears in the directory immediately. Scoped to the
    // desktop table: the responsive layout renders the same value twice.
    await findInDirectory(page, onboarded.student.number);

    // The credential actually authenticates the account.
    await signInAsStudent(page, onboarded);
    await expect(page).toHaveURL(new RegExp(`/${LOCALE}/app$`));

    // A student holds no staff modules.
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Students" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Immigration" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "My profile" })).toBeVisible();

    expect(failures).toEqual([]);
  });

  test("student reaches their own profile without knowing its identifier", async ({
    page,
  }) => {
    const failures = trackPageHealth(page);
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    await page.goto(app("/app/profile"));
    // The resolver forwards to the canonical profile route.
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
    await expect(
      page.getByText(onboarded.student.number).first(),
    ).toBeVisible();
    expect(failures).toEqual([]);
  });

  test("student edits their own contact details and the change persists", async ({
    page,
  }) => {
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    await page.goto(app("/app/profile"));
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });

    await page.getByRole("button", { name: /edit my details/i }).click();
    const dialog = page.getByRole("dialog");
    const phone = `+86-138-${onboarded.student.number.slice(-7)}`;
    await dialog.getByLabel(/^phone/i).fill(phone);
    await dialog.getByRole("button", { name: /^save$/i }).click();

    // The value survives a reload, so it reached the database.
    await page.reload();
    // The same number is intentionally rendered in the profile header and the
    // Overview tab; either occurrence proves the persisted value.
    await expect(page.getByText(phone).first()).toBeVisible({ timeout: 25_000 });
  });

  test("student cannot declare a placement after direct writes are retired", async ({
    page,
  }) => {
    const failures = trackPageHealth(page);
    const onboarded = await onboardStudent(page);

    await signInAsStudent(page, onboarded);
    await page.goto(app("/app/profile"));
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
    await page.getByRole("tab", { name: "Academic" }).click();

    // Phase 8a retires the student-facing direct placement form. The API's
    // can_select=false is what removes it; the office-owned text replaces it.
    await expect(
      page.getByText(/academic placement is recorded by the international office/i),
    ).toBeVisible({ timeout: 25_000 });
    await expect(page.getByLabel("Intake period")).toHaveCount(0);
    await expect(page.getByLabel("Program offering")).toHaveCount(0);
    expect(failures).toEqual([]);
  });

  test("student cannot reach the staff directory", async ({ page }) => {
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    await page.goto(app("/app/students"));
    await expect(
      page.getByText(/do not have permission to view the student directory/i),
    ).toBeVisible({ timeout: 25_000 });
  });

  test("student cannot reach the immigration overview", async ({ page }) => {
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    await page.goto(app("/app/immigration"));
    await expect(
      page.getByText(/restricted to the international office/i),
    ).toBeVisible({ timeout: 25_000 });

    // The API refuses independently of the UI, and returns no cohort data.
    const response = await page.request.get(
      `${API_BASE}/api/v1/immigration/overview`,
    );
    expect(response.status()).toBe(403);
  });

  test("student cannot onboard another student", async ({ page }) => {
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    // Direct API call, bypassing the UI entirely.
    const response = await page.request.post(
      `${API_BASE}/api/v1/students/onboard`,
      {
        data: {
          student_id: `STU-HACK-${onboarded.student.number.slice(-7)}`,
          first_name: "Hack",
          last_name: "Attempt",
          email: `hack-${Date.now()}@example.com`,
        },
      },
    );
    expect(response.status()).toBe(403);
  });

  test("student cannot read another student's record", async ({ page }) => {
    const onboarded = await onboardStudent(page);

    // Capture a different student's id while still signed in as admin.
    await page.goto(app("/app/students"));
    const otherHref = await page
      .locator(`a[href*="/app/students/"]:visible`)
      .first()
      .getAttribute("href");
    const otherId = otherHref?.match(/[0-9a-f-]{36}/)?.[0];
    expect(otherId).toBeTruthy();

    await signInAsStudent(page, onboarded);
    const response = await page.request.get(`${API_BASE}/api/v1/students/${otherId}`);
    expect(response.status()).toBe(403);
  });
});

test.describe("account security", () => {
  test("a student changes their password and the old one stops working", async ({
    page,
  }) => {
    const onboarded = await onboardStudent(page);
    // Deliberately stay on the temporary password: this test is the restricted
    // state, and the change below is the action under test.
    await signInAsStudent(page, onboarded, { completeChange: false });

    await page.goto(app("/app/settings"));
    await expect(page.getByRole("heading", { name: /settings/i })).toBeVisible();
    // The temporary-password banner is shown while the issued password is live.
    await expect(page.getByText(/temporary password/i).first()).toBeVisible();

    await page.getByLabel(/current password/i).fill(onboarded.password);
    await page.getByLabel(/^new password$/i).fill(onboarded.student.password);
    await page.getByLabel(/confirm new password/i).fill(onboarded.student.password);
    await page.getByRole("button", { name: /change password/i }).click();

    await expect(page.getByText(/password was changed/i)).toBeVisible({
      timeout: 25_000,
    });

    // The new credential works and the issued one no longer does.
    await signOut(page);
    await login(page, {
      email: onboarded.student.email,
      password: onboarded.student.password,
    });

    await signOut(page);
    await page.goto(app("/login"));
    await page.getByLabel(/email/i).fill(onboarded.student.email);
    await page.getByLabel(/password/i).fill(onboarded.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByText(/incorrect email or password/i)).toBeVisible({
      timeout: 25_000,
    });
  });

  test("settings lists active sessions and distinguishes this device", async ({
    page,
  }) => {
    await login(page, ADMIN);
    await page.goto(app("/app/settings"));
    await expect(page.getByText(/active sessions/i)).toBeVisible();
    await expect(page.getByText(/this device/i).first()).toBeVisible();

    // The page must never render a session token.
    const body = await page.locator("body").innerText();
    expect(body.toLowerCase()).not.toContain("token_hash");
  });

  test("settings is reachable for every role", async ({ page }) => {
    await login(page, TEACHER);
    await page.goto(app("/app/settings"));
    await expect(page.getByRole("heading", { name: /settings/i })).toBeVisible();
    // A teacher has no account-administration section.
    await expect(page.getByRole("heading", { name: /^administration$/i })).toHaveCount(0);
  });
});

/**
 * Walk the estate down to a room that has a free bed.
 *
 * Deliberately not a hard-coded room: the housing module is data-driven, and a
 * test that assumed "Building 18 Room 101" would break the moment the seed or
 * the occupancy changed.
 */
async function openRoomWithSpace(page: Page) {
  /**
   * Children of the current page's URL.
   *
   * Scoped this way because breadcrumbs link to the ancestors — a plain
   * `a[href*="/app/housing/"]` would match the "Housing" crumb and navigate
   * back up instead of down into the room grid.
   */
  const children = () =>
    page.locator(`main a[href*="${new URL(page.url()).pathname}/"]`);

  // `count()` does not wait, and the grid arrives with a client-side fetch, so
  // visibility is asserted before anything is counted or clicked.
  await page.goto(app("/app/housing"));
  await expect(children().first()).toBeVisible({ timeout: 25_000 });
  await children().first().click(); // a building
  await page.waitForURL(/\/app\/housing\/[0-9a-f-]{36}$/, { timeout: 25_000 });

  await expect(children().first()).toBeVisible({ timeout: 25_000 });
  await children().first().click(); // its first floor
  await page.waitForURL(/\/app\/housing\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/, {
    timeout: 25_000,
  });

  // A room whose occupancy count is below its capacity.
  const rooms = children();
  await expect(rooms.first()).toBeVisible({ timeout: 25_000 });
  const roomCount = await rooms.count();
  for (let i = 0; i < roomCount; i += 1) {
    const match = (await rooms.nth(i).innerText()).match(/(\d+)\s*\/\s*(\d+)/);
    if (match && Number(match[1]) < Number(match[2])) {
      await rooms.nth(i).click();
      await page.waitForURL(
        /\/app\/housing\/[0-9a-f-]{36}\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/,
        { timeout: 25_000 },
      );
      return;
    }
  }

  throw new Error("no room with a free bed was found on the first floor");
}

test.describe("housing administration", () => {
  test("admin assigns a student to a bed, then moves them", async ({ page }) => {
    const failures = trackPageHealth(page);
    const onboarded = await onboardStudent(page);

    await openRoomWithSpace(page);
    // Anchored on the number: "Room administration" is also a heading here.
    await expect(page.getByRole("heading", { name: /^Room \d+/ })).toBeVisible();

    // Before Stage 8B this button did not exist anywhere in the UI: assignment
    // was API-only, so "assign a student" was not an operable workflow.
    await page.getByRole("button", { name: /assign student/i }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.getByLabel(/find student/i).fill(onboarded.student.lastName);
    await dialog.getByRole("radio").first().check();
    await dialog.getByRole("button", { name: /confirm/i }).click();

    await expect(dialog).toBeHidden({ timeout: 25_000 });
    await expect(page.getByText(onboarded.student.lastName).first()).toBeVisible({
      timeout: 25_000,
    });

    // The write reached the database: after a reload the bed is still taken,
    // and the action on it has become "move" rather than "assign".
    await page.reload();
    await expect(page.getByText(onboarded.student.lastName).first()).toBeVisible({
      timeout: 25_000,
    });
    await expect(page.getByRole("button", { name: /^move$/i }).first()).toBeVisible({
      timeout: 25_000,
    });

    // The occupant name is a link to the student-record route. Before the fix
    // it was built from the login-account id, which the profile endpoint cannot
    // resolve. Following it is the original reported failure mode.
    const occupant = page
      .getByRole("link", {
        name: `${onboarded.student.firstName} ${onboarded.student.lastName}`,
      })
      .first();
    await expect(occupant).toBeVisible({ timeout: 25_000 });
    await occupant.click();
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
    await expect(page.getByText(onboarded.student.number).first()).toBeVisible({
      timeout: 25_000,
    });
    await page.goBack();
    await page.waitForURL(
      /\/app\/housing\/[0-9a-f-]{36}\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/,
      { timeout: 25_000 },
    );

    // Move the student to another free bed; the old bed is vacated.
    await page.getByRole("button", { name: /^move$/i }).first().click();
    const moveDialog = page.getByRole("dialog");
    await expect(moveDialog).toBeVisible();
    await moveDialog.getByLabel(/destination room/i).selectOption({ index: 1 });
    await moveDialog.getByLabel(/destination bed/i).selectOption({ index: 1 });
    await moveDialog.getByRole("button", { name: /confirm/i }).click();
    await expect(moveDialog).toBeHidden({ timeout: 25_000 });

    expect(failures).toEqual([]);
  });

  test("a student cannot assign anyone to a bed", async ({ page }) => {
    const onboarded = await onboardStudent(page);
    await signInAsStudent(page, onboarded);

    // The room page is refused outright, so there is no administration surface
    // to find; the API is checked directly as the real boundary.
    const rooms = await page.request.get(`${API_BASE}/api/v1/housing/overview`);
    expect(rooms.status()).toBe(403);

    // A well-formed body: a malformed one would be rejected by validation
    // before authorization even ran, and would prove nothing.
    const assign = await page.request.post(
      `${API_BASE}/api/v1/housing/assignments`,
      {
        data: {
          student_id: crypto.randomUUID(),
          bed_id: crypto.randomUUID(),
          start_date: "2026-09-01T00:00:00Z",
        },
      },
    );
    expect(assign.status()).toBe(403);
  });
});

test.describe("staff administration", () => {
  test("admin bulk-changes student status from the directory", async ({ page }) => {
    const onboarded = await onboardStudent(page);

    // Select the student created for this run.
    const row = await findInDirectory(page, onboarded.student.number);
    await row
      .getByRole("checkbox", {
        name: `Select ${onboarded.student.firstName} ${onboarded.student.lastName}`,
      })
      .check();

    await expect(page.getByText(/1 selected/i)).toBeVisible();
    await page.getByRole("button", { name: /change status/i }).click();

    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/new status/i).selectOption("SUSPENDED");
    await dialog.getByRole("button", { name: /^apply$/i }).click();

    await expect(dialog.getByText(/updated/i).first()).toBeVisible({
      timeout: 25_000,
    });
  });

  test("teacher cannot change student status", async ({ page }) => {
    await login(page, TEACHER);
    await page.goto(app("/app/students"));

    // No selection column at all, because a teacher holds no `student.edit`.
    await expect(page.getByRole("checkbox")).toHaveCount(0);
  });

  test("profile edit saves and refreshes without a manual reload", async ({ page }) => {
    const onboarded = await onboardStudent(page);

    const row = await findInDirectory(page, onboarded.student.number);
    await row
      .getByRole("link", { name: `${onboarded.student.lastName}, ${onboarded.student.firstName}` })
      .first()
      .click();
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/);

    await page.getByRole("button", { name: /^edit$/i }).click();
    const dialog = page.getByRole("dialog");
    const preferred = `E2E-${onboarded.student.number.slice(-7)}`;
    await dialog.getByLabel(/preferred name/i).fill(preferred);
    await dialog.getByRole("button", { name: /^save$/i }).click();

    // The header reflects the change without a page reload.
    await expect(page.getByText(preferred).first()).toBeVisible({ timeout: 25_000 });
  });

  test("student profile still loads after the account lifecycle changes", async ({
    page,
  }) => {
    await login(page, ADMIN);
    await page.goto(app("/app/students"));
    await page.locator(`a[href*="${app("/app/students/")}"]:visible`).first().click();
    await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/);
    await expect(page.getByRole("tab", { name: "Overview", exact: true })).toBeVisible();
  });
});
