import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app, signOutViaAccountMenu } from "./accounts";

/**
 * Phase 4 programme-change workflow.
 *
 * Synthetic data only, in the disposable E2E stack. The test proves a
 * request changes nothing, one Management approval applies the change, the
 * originally admitted programme remains visible, and the same episode is
 * preserved. A second pass checks the Arabic (RTL) rendering of the timeline.
 */

async function login(page: Page, user: { email: string; password: string }, prefix = "/en") {
  await page.goto(`${prefix}/login`);
  await page.getByLabel(/email|البريد/i).fill(user.email);
  await page.getByLabel(/password|كلمة المرور/i).fill(user.password);
  await page.getByRole("button").filter({ hasText: /sign in|تسجيل الدخول/i }).click();
  await page.waitForURL(new RegExp(`${prefix}/app`), { timeout: 25_000 });
}

async function json<T>(response: APIResponse, expected = 200): Promise<T> {
  const body = await response.text();
  expect(response.status(), body).toBe(expected);
  return JSON.parse(body) as T;
}

async function post<T>(page: Page, path: string, data: unknown, expected = 201): Promise<T> {
  return json<T>(
    await page.request.post(`${API_BASE}${path}`, { data }),
    expected,
  );
}

test.describe.serial("programme change within one admission episode", () => {
  let studentId = "";
  let intakeName = "";
  let admittedProgramName = "";
  let newProgramName = "";
  let admittedProgramId = "";
  let newProgramId = "";

  test("requests, approves, and preserves the original programme and episode", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now().toString().slice(-7);
    await login(page, USERS.admin);

    const programs = await json<{
      items: { id: string; code: string; name: string; major_id: string; status: string }[];
    }>(await page.request.get(`${API_BASE}/api/v1/academics/programs?page_size=100`));
    const active = programs.items.filter((program) => program.status === "ACTIVE");
    if (active.length < 2) {
      const created = await post<{ id: string; name: string }>(
        page,
        "/api/v1/academics/programs",
        {
          major_id: active[0]?.major_id,
          code: `E2EP${stamp}`,
          name: `E2E Programme ${stamp}`,
        },
      );
      active.push({ ...created, code: `E2EP${stamp}`, major_id: "", status: "ACTIVE" });
    }
    const admittedProgram = active[0];
    const newProgram = active[1];
    admittedProgramId = admittedProgram.id;
    admittedProgramName = admittedProgram.name;
    newProgramId = newProgram.id;
    newProgramName = newProgram.name;

    const intake = await post<{ id: string; name: string }>(
      page,
      "/api/v1/academics/periods",
      {
        name: `E2E programme intake ${stamp}`,
        code: `EPC${stamp}`,
        start_date: "2034-09-01",
        end_date: "2034-12-20",
        status: "ACTIVE",
      },
    );
    intakeName = intake.name;

    const admittedOffering = await post<{ id: string }>(
      page,
      "/api/v1/academics/program-offerings",
      {
        academic_period_id: intake.id,
        source_id: `e2e-change-admitted-${stamp}`,
        name: `E2E admitted offering ${stamp}`,
        program_id: admittedProgram.id,
      },
    );
    const newOffering = await post<{ id: string }>(
      page,
      "/api/v1/academics/program-offerings",
      {
        academic_period_id: intake.id,
        source_id: `e2e-change-new-${stamp}`,
        name: `E2E new offering ${stamp}`,
        program_id: newProgram.id,
      },
    );

    const onboarded = await post<{ student: { id: string } }>(
      page,
      "/api/v1/students/onboard",
      {
        student_id: `STU-CHANGE-${stamp}`,
        first_name: "Programme",
        last_name: `Change${stamp}`,
        email: `programme-change-${stamp}@example.com`,
        program_offering_id: admittedOffering.id,
        admission_intake_id: intake.id,
        initial_admission_status: "ACTIVE",
      },
    );
    studentId = onboarded.student.id;

    const before = await json<{
      items: { id: string; admitted_program_id: string; current_program_id: string }[];
    }>(await page.request.get(`${API_BASE}/api/v1/students/${studentId}/admissions`));
    expect(before.items).toHaveLength(1);
    const admissionId = before.items[0].id;

    await page.goto(app(`/app/students/${studentId}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    const section = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Programme change", exact: true }),
    });
    await expect(section).toBeVisible();
    await expect(section).toContainText(admittedProgramName);
    await expect(section).toContainText(intakeName);

    await section.getByRole("button", { name: "Request change" }).click();
    let dialog = page.getByRole("dialog");
    await dialog
      .getByLabel("New programme", { exact: true })
      .selectOption(newProgram.id);
    await dialog
      .getByLabel("New programme offering (optional)", { exact: true })
      .selectOption(newOffering.id);
    await dialog.getByLabel("Reason").fill("E2E approved same-intake programme transfer");
    await dialog.getByRole("button", { name: "Submit request" }).click();
    await expect(
      page.getByText("Programme change requested. It is pending approval."),
    ).toBeVisible();
    await expect(section.getByText("Pending approval").first()).toBeVisible();

    const pending = await json<{
      items: {
        id: string;
        status: string;
        current_program_id: string;
        admitted_program_id: string;
      }[];
    }>(await page.request.get(`${API_BASE}/api/v1/students/${studentId}/admissions`));
    expect(pending.items).toHaveLength(1);
    expect(pending.items[0].admitted_program_id).toBe(admittedProgram.id);
    expect(pending.items[0].current_program_id).toBe(admittedProgram.id);

    await signOutViaAccountMenu(page);
    await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
    await login(page, USERS.management);
    await page.goto(app(`/app/students/${studentId}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();

    const managerSection = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Programme change", exact: true }),
    });
    await expect(managerSection.getByText("Pending approval").first()).toBeVisible();
    await managerSection.getByRole("button", { name: "Review" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Decision reason").fill("E2E Management approval");
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Programme change approved.")).toBeVisible();

    await expect(managerSection).toContainText(newProgramName);
    await expect(managerSection).toContainText(admittedProgramName);
    await expect(managerSection).toContainText("Approved by Management User");

    const after = await json<{
      items: {
        id: string;
        admitted_program_id: string;
        current_program_id: string;
      }[];
    }>(await page.request.get(`${API_BASE}/api/v1/students/${studentId}/admissions`));
    expect(after.items).toHaveLength(1);
    expect(after.items[0].id).toBe(admissionId);
    expect(after.items[0].admitted_program_id).toBe(admittedProgram.id);
    expect(after.items[0].current_program_id).toBe(newProgram.id);

    const changes = await json<{ items: { status: string }[] }>(
      await page.request.get(`${API_BASE}/api/v1/students/${studentId}/admission-changes`),
    );
    expect(changes.items).toHaveLength(1);
    expect(changes.items[0].status).toBe("APPROVED");

    await signOutViaAccountMenu(page);
    await page.waitForURL(/\/en\/login/, { timeout: 25_000 });
    await login(page, USERS.admin);
    await page.goto(app("/app/audit"));
    const actionFilter = page.getByLabel("Action", { exact: true });
    await expect(
      actionFilter.locator('option[value="academic.admission.change_approved"]'),
    ).toHaveText("Programme change approved");
    await actionFilter.selectOption("academic.admission.change_approved");
    await expect(
      page.getByRole("row").filter({ hasText: "Programme change approved" }).first(),
    ).toBeVisible();
  });

  test("arabic timeline uses RTL and localized programme-change labels", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await login(page, USERS.admin, "/ar");
    await page.goto(`/ar/app/students/${studentId}`);
    await page.getByRole("tab", { name: "الأكاديمي", exact: true }).click();

    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    const section = page.locator("section").filter({
      has: page.getByRole("heading", { name: "تغيير البرنامج", exact: true }),
    });
    await expect(section).toBeVisible();
    await expect(section.getByText("البرنامج المقبول به أصلاً")).toBeVisible();
    await expect(section.getByText("البرنامج الحالي")).toBeVisible();
    await expect(section.getByText(newProgramName).first()).toBeVisible();
    await expect(section.getByText(admittedProgramName).first()).toBeVisible();

    const box = await section.boundingBox();
    const main = page.locator("main").first();
    const mainBox = await main.boundingBox();
    expect(box).not.toBeNull();
    expect(mainBox).not.toBeNull();
    if (box && mainBox) {
      expect(box.width).toBeLessThanOrEqual(mainBox.width + 1);
      expect(box.x).toBeGreaterThanOrEqual(mainBox.x);
    }
  });
});
