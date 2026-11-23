import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Phase 2 migration verification console.
 *
 * This spec runs against the disposable E2E stack, which enables the two
 * admission flags only for the test composition. It creates a synthetic
 * student, four intakes and three migrated candidates so one browser session
 * can prove the complete trust-state path:
 *
 *   UNVERIFIED -> VERIFIED -> REVOKED
 *   UNVERIFIED -> DISPUTED (conflicting snapshots)
 *   VERIFIED, not the pointer -> ADMIN pointer correction
 *
 * Supporting UI and API evidence is asserted throughout; the spec never
 * rewrites historical acts or calls a bulk verification endpoint.
 */

const PASSWORD = process.env.E2E_PASSWORD ?? "password123";

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
  await page.waitForURL(new RegExp(`/en/app`), { timeout: 25_000 });
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
}

async function expectOk(response: APIResponse, expected: number) {
  const body = await response.text();
  expect(response.status(), body).toBe(expected);
  return body ? JSON.parse(body) : null;
}

async function post<T>(
  page: Page,
  path: string,
  data: unknown,
  expected = 201,
): Promise<T> {
  const response = await page.request.post(`${API_BASE}${path}`, { data });
  return (await expectOk(response, expected)) as T;
}

test.describe("migration verification console", () => {
  test("queue, dual confirmation, revocation, dispute and pointer correction", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const failures = trackPageHealth(page);
    const stamp = Date.now().toString().slice(-7);
    const studentNumber = `STU-VER-${stamp}`;

    await login(page, USERS.admin);

    const onboarded = await post<{
      student: { id: string; student_id: string };
    }>(page, "/api/v1/students/onboard", {
      student_id: studentNumber,
      first_name: "Verification",
      last_name: `Candidate${stamp}`,
      email: `verification-${stamp}@example.com`,
    });
    const studentId = onboarded.student.id;
    expect(onboarded.student.student_id).toBe(studentNumber);

    const programs = await page.request.get(
      `${API_BASE}/api/v1/academics/programs`,
    );
    const program = ((await programs.json()) as { items: { id: string }[] })
      .items[0];

    const intakes: { id: string; name: string }[] = [];
    const offerings: string[] = [];
    for (const [index, year] of [2025, 2026, 2027, 2028].entries()) {
      const intakeName = `E2E verification intake ${stamp}-${index + 1}`;
      const period = await post<{ id: string; name: string }>(
        page,
        "/api/v1/academics/periods",
        {
          name: intakeName,
          code: `EV${stamp}${index + 1}`,
          start_date: `${year}-09-01`,
          end_date: `${year}-12-20`,
          status: "ACTIVE",
        },
      );
      intakes.push({ id: period.id, name: period.name });
      const offering = await post<{ id: string }>(
        page,
        "/api/v1/academics/program-offerings",
        {
          academic_period_id: period.id,
          source_id: `e2e-verification-${stamp}-${index + 1}`,
          name: `E2E verification offering ${stamp}-${index + 1}`,
          program_id: program.id,
        },
      );
      offerings.push(offering.id);
    }

    const candidate1 = await post<{ id: string }>(
      page,
      `/api/v1/students/${studentId}/admissions/migrated`,
      {
        admission_intake_id: intakes[0].id,
        program_offering_id: offerings[0],
      },
    );
    await post(
      page,
      `/api/v1/students/${studentId}/admissions/migrated`,
      {
        admission_intake_id: intakes[1].id,
        program_offering_id: offerings[1],
      },
    );

    await signOut(page);
    await login(page, USERS.management);

    await expect(
      page.getByRole("link", { name: "Admission verification", exact: true }),
    ).toBeVisible();
    await page.goto(app("/app/admissions/verification"));
    await expect(
      page.getByRole("heading", { name: "Admission verification" }),
    ).toBeVisible();

    // Search proves the queue is server-filtered, not a client-side slice.
    await page.getByRole("searchbox").fill(studentNumber);
    const c1Row = page.getByRole("row").filter({ hasText: intakes[0].name });
    await expect(c1Row).toBeVisible();
    await page.getByLabel("Trust state").selectOption("REVOKED");
    await expect(c1Row).toHaveCount(0);
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await expect(c1Row).toBeVisible();

    await c1Row.getByRole("button", { name: "Review" }).click();
    let detail = page.getByRole("dialog");
    await expect(detail.getByText("Not confirmed").first()).toBeVisible();
    await expect(
      detail.getByRole("button", { name: "Confirm Admin" }),
    ).toHaveCount(0);

    await detail
      .getByRole("button", { name: "Confirm Management" })
      .click();
    let action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence type").selectOption("ADMISSION_LETTER");
    await action
      .getByLabel("Evidence reference")
      .fill(`Management evidence ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await expect(
      detail.getByText("Confirmation", { exact: true }),
    ).toBeVisible();
    await expect(detail.getByText("Management User").first()).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await signOut(page);
    await login(page, USERS.admin);
    await page.goto(app("/app/admissions/verification"));
    await page.getByRole("searchbox").fill(studentNumber);
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await expect(c1Row).toBeVisible();
    await c1Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await expect(detail.getByText("Confirmed", { exact: true }).first()).toBeVisible();
    await detail.getByRole("button", { name: "Confirm Admin" }).click();
    action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence type").selectOption("ENROLMENT_RECORD");
    await action.getByLabel("Evidence reference").fill(`Admin evidence ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await page.getByLabel("Trust state").selectOption("VERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    await expect(c1Row).toBeVisible();
    await c1Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await expect(detail.getByText("Current original")).toBeVisible();
    await expect(
      detail.getByRole("button", { name: "Correct pointer" }),
    ).toHaveCount(0);
    await expect(
      detail.getByText("Confirmation", { exact: true }),
    ).toHaveCount(2);
    await expect(detail.getByText("Admin User").first()).toBeVisible();

    await detail.getByRole("button", { name: "Revoke Admin" }).click();
    action = page.getByRole("dialog").last();
    await action
      .getByLabel("Revocation reason")
      .fill("E2E revocation: evidence needs a second review.");
    await action.getByRole("button", { name: "Revoke confirmation" }).click();
    await expect(page.getByText("Confirmation revoked.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("REVOKED");
    await page.getByRole("searchbox").fill(studentNumber);
    await expect(c1Row).toBeVisible();
    await c1Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await expect(
      detail.getByText("Revocation", { exact: true }),
    ).toBeVisible();
    await expect(
      detail.getByText(/evidence needs a second review/i),
    ).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    // Candidate 3 is added through the console form, not the API fixture.
    await page.getByRole("button", { name: "Add candidate" }).click();
    const createForm = page.getByRole("dialog").last();
    await createForm.getByRole("searchbox").fill(studentNumber);
    await expect(
      createForm
        .getByLabel("Student")
        .locator(`option[value="${studentId}"]`),
    ).toHaveCount(1);
    await createForm.getByLabel("Student", { exact: true }).selectOption(studentId);
    await expect(
      createForm
        .getByLabel("Admission intake")
        .locator(`option[value="${intakes[3].id}"]`),
    ).toHaveCount(1);
    await createForm
      .getByLabel("Admission intake")
      .selectOption(intakes[3].id);
    await expect(
      createForm
        .getByLabel("Program offering")
        .locator(`option[value="${offerings[3]}"]`),
    ).toHaveCount(1);
    await createForm
      .getByLabel("Program offering")
      .selectOption(offerings[3]);
    await createForm
      .getByRole("button", { name: "Add candidate" })
      .click();
    await expect(page.getByText("Migration candidate added.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    // Candidate 2: the two confirmations will carry different snapshots.
    await signOut(page);
    await login(page, USERS.management);
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    const c2Row = page.getByRole("row").filter({ hasText: intakes[1].name });
    await expect(c2Row).toBeVisible();
    await c2Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await detail
      .getByRole("button", { name: "Confirm Management" })
      .click();
    action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence reference").fill(`Dispute evidence ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await signOut(page);
    await login(page, USERS.admin);
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    const c2BeforeRow = page
      .getByRole("row")
      .filter({ hasText: intakes[1].name });
    await expect(c2BeforeRow).toBeVisible();
    await c2BeforeRow.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "Edit candidate" }).click();
    const editForm = page.getByRole("dialog").last();
    await expect(
      editForm
        .getByLabel("Admission intake")
        .locator(`option[value="${intakes[2].id}"]`),
    ).toHaveCount(1);
    await editForm
      .getByLabel("Admission intake")
      .selectOption(intakes[2].id);
    await expect(
      editForm
        .getByLabel("Program offering")
        .locator(`option[value="${offerings[2]}"]`),
    ).toHaveCount(1);
    await editForm
      .getByLabel("Program offering")
      .selectOption(offerings[2]);
    await editForm
      .getByRole("button", { name: "Save correction" })
      .click();
    await expect(
      page.getByText("Migration candidate corrected."),
    ).toBeVisible();
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    const c2ChangedRow = page
      .getByRole("row")
      .filter({ hasText: intakes[2].name });
    await expect(c2ChangedRow).toBeVisible();
    await c2ChangedRow.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "Confirm Admin" }).click();
    action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence reference").fill(`Admin dispute ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await page.getByLabel("Trust state").selectOption("DISPUTED");
    await page.getByRole("searchbox").fill(studentNumber);
    await expect(c2ChangedRow).toBeVisible();
    await c2ChangedRow.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await expect(
      detail.getByText("Conflicting candidate snapshots"),
    ).toBeVisible();
    await expect(detail.getByText(intakes[1].name).first()).toBeVisible();
    await expect(detail.getByText(intakes[2].name).first()).toBeVisible();
    await expect(
      detail.getByRole("button", { name: "Correct pointer" }),
    ).toHaveCount(0);
    await page.goto(app("/app/admissions/verification"));

    // Candidate 3: verify it after the pointer already belongs to candidate 1.
    await signOut(page);
    await login(page, USERS.management);
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    const c3Row = page.getByRole("row").filter({ hasText: intakes[3].name });
    await expect(c3Row).toBeVisible();
    await c3Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await detail
      .getByRole("button", { name: "Confirm Management" })
      .click();
    action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence reference").fill(`Pointer evidence ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await signOut(page);
    await login(page, USERS.admin);
    await page.goto(app("/app/admissions/verification"));
    await page.getByLabel("Trust state").selectOption("UNVERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    await c3Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "Confirm Admin" }).click();
    action = page.getByRole("dialog").last();
    await action.getByLabel("Evidence reference").fill(`Pointer admin ${stamp}`);
    await action.getByRole("button", { name: "Record confirmation" }).click();
    await expect(page.getByText("Confirmation recorded.")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await page.getByLabel("Trust state").selectOption("VERIFIED");
    await page.getByRole("searchbox").fill(studentNumber);
    await expect(c3Row).toBeVisible();
    await c3Row.getByRole("button", { name: "Review" }).click();
    detail = page.getByRole("dialog");
    await expect(detail.getByText("Another admission")).toBeVisible();
    const correct = detail.getByRole("button", { name: "Correct pointer" });
    await expect(correct).toBeVisible();
    await correct.click();
    action = page.getByRole("dialog").last();
    await action
      .getByLabel("Correction reason")
      .fill("E2E: candidate 3 is the earlier original admission.");
    await action
      .getByLabel("Evidence reference")
      .fill(`Pointer correction ${stamp}`);
    await action
      .getByRole("checkbox", { name: /replaces the original-admission pointer/ })
      .check();
    await action.getByRole("button", { name: "Correct pointer" }).click();
    await expect(
      page.getByText("Original-admission pointer corrected."),
    ).toBeVisible();
    await expect(detail.getByText("Current original")).toBeVisible();
    await page.goto(app("/app/admissions/verification"));

    await signOut(page);
    await login(page, USERS.teacher);
    await expect(
      page.getByRole("link", { name: "Admission verification", exact: true }),
    ).toHaveCount(0);
    await page.goto(app("/app/admissions/verification"));
    await expect(
      page.getByText("You do not have permission to view admission verification."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Review" })).toHaveCount(0);

    expect(failures).toEqual([]);
    expect(candidate1.id).toBeTruthy();
  });

  test("arabic console renders RTL with localized controls", async ({ page }) => {
    await page.goto("/ar/login");
    await page.getByLabel(/البريد/).fill(USERS.admin.email);
    await page.getByLabel(/كلمة المرور/).fill(PASSWORD);
    await page
      .getByRole("button")
      .filter({ hasText: /تسجيل الدخول/ })
      .click();
    await page.waitForURL(/\/ar\/app/, { timeout: 25_000 });

    await page.goto("/ar/app/admissions/verification");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(
      page.getByRole("heading", { name: "التحقق من القبول" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "التحقق من القبول", exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("حالة الثقة")).toBeVisible();
    await expect(page.getByRole("searchbox")).toBeVisible();

    const sidebar = page.locator("aside").first();
    const main = page.locator("main").first();
    const sidebarBox = await sidebar.boundingBox();
    const mainBox = await main.boundingBox();
    expect(sidebarBox).not.toBeNull();
    expect(mainBox).not.toBeNull();
    if (sidebarBox && mainBox) {
      expect(sidebarBox.x).toBeGreaterThan(mainBox.x);
    }
  });
});
