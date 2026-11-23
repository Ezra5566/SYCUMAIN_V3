import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Phase 7 administrative corrections.
 *
 * Synthetic data only. ADMIN corrects a withdrawn episode directly; MANAGEMENT
 * submits the same kind of correction as a request, which ADMIN reviews. Both
 * dialogs show the recorded end state and require an explicit confirmation.
 */

async function login(page: Page, user: { email: string; password: string }) {
  await page.goto(app("/login"));
  await page.getByLabel(/email/i).fill(user.email);
  await page.getByLabel(/password/i).fill(user.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL(/\/en\/app/, { timeout: 25_000 });
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
  return (await expectOk(
    await page.request.post(`${API_BASE}${path}`, { data }),
    expected,
  )) as T;
}

async function createWithdrawnStudent(
  page: Page,
  stamp: string,
  suffix: string,
  intakeId: string,
  offeringId: string,
) {
  const onboarded = await post<{ student: { id: string } }>(
    page,
    "/api/v1/students/onboard",
    {
      student_id: `STU-CORR-${stamp}-${suffix}`,
      first_name: "Correction",
      last_name: `Candidate${stamp}${suffix}`,
      email: `correction-${stamp}-${suffix}@example.com`,
    },
  );
  const studentId = onboarded.student.id;
  const admission = await post<{ id: string }>(
    page,
    `/api/v1/students/${studentId}/admissions`,
    {
      admission_intake_id: intakeId,
      program_offering_id: offeringId,
      initial_status: "ACTIVE",
    },
  );
  await post(
    page,
    `/api/v1/students/${studentId}/admissions/${admission.id}/status`,
    { status: "WITHDRAWN", reason: "E2E withdrawal recorded in error" },
    200,
  );
  return studentId;
}

function programmeSection(page: Page) {
  return page.locator("section").filter({
    has: page.getByRole("heading", { name: "Programme change", exact: true }),
  });
}

test.describe.serial("administrative admission corrections", () => {
  test("ADMIN corrects directly and MANAGEMENT requests an ADMIN-reviewed correction", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    const stamp = Date.now().toString().slice(-7);

    await login(page, USERS.admin);
    const programmes = (await expectOk(
      await page.request.get(`${API_BASE}/api/v1/academics/programs`),
      200,
    )) as { items: { id: string }[] };
    const programmeId = programmes.items[0].id;
    const intake = await post<{ id: string; name: string }>(
      page,
      "/api/v1/academics/periods",
      {
        name: `E2E correction intake ${stamp}`,
        code: `ECR${stamp}`,
        start_date: "2035-09-01",
        end_date: "2035-12-20",
        status: "ACTIVE",
      },
    );
    const offering = await post<{ id: string }>(
      page,
      "/api/v1/academics/program-offerings",
      {
        academic_period_id: intake.id,
        source_id: `e2e-correction-${stamp}`,
        name: `E2E correction offering ${stamp}`,
        program_id: programmeId,
      },
    );

    const directStudent = await createWithdrawnStudent(
      page,
      stamp,
      "A",
      intake.id,
      offering.id,
    );
    await page.goto(app(`/app/students/${directStudent}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    let section = programmeSection(page);
    await expect(section.getByText("Withdrawn", { exact: true }).first()).toBeVisible({
      timeout: 25_000,
    });

    await section.getByRole("button", { name: "Correct status" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Current record")).toBeVisible();
    await expect(dialog.getByText(intake.name)).toBeVisible();
    await expect(dialog.getByText("Ended", { exact: false })).toBeVisible();
    await expect(dialog.getByText("E2E withdrawal recorded in error")).toBeVisible();
    await dialog.getByLabel("Corrected status").selectOption("ACTIVE");
    await dialog
      .getByLabel("Correction reason")
      .fill("Registrar confirmed the withdrawal was recorded against the wrong student");
    const directSubmit = dialog.getByRole("button", { name: "Correct status" });
    await expect(directSubmit).toBeDisabled();
    await dialog
      .getByRole("checkbox", { name: /erroneous data/ })
      .check();
    await directSubmit.click();
    await expect(page.getByText("Admission status corrected.")).toBeVisible();
    section = programmeSection(page);
    await expect(section.getByText("Active", { exact: true }).first()).toBeVisible();

    const directAdmissions = (await expectOk(
      await page.request.get(
        `${API_BASE}/api/v1/students/${directStudent}/admissions`,
      ),
      200,
    )) as { items: { status: string }[] };
    expect(directAdmissions.items[0].status).toBe("ACTIVE");

    const requestedStudent = await createWithdrawnStudent(
      page,
      stamp,
      "B",
      intake.id,
      offering.id,
    );
    await signOut(page);
    await login(page, USERS.management);
    await page.goto(app(`/app/students/${requestedStudent}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    section = programmeSection(page);
    await expect(section.getByRole("button", { name: "Correct status" })).toHaveCount(0);
    await section.getByRole("button", { name: "Request status correction" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Request an admission status correction")).toBeVisible();
    await dialog.getByLabel("Corrected status").selectOption("ACTIVE");
    await dialog
      .getByLabel("Correction reason")
      .fill("Management verified the student never withdrew from the programme");
    await dialog
      .getByRole("checkbox", { name: /erroneous data/ })
      .check();
    await dialog.getByRole("button", { name: "Submit request" }).click();
    await expect(page.getByText("Status correction request submitted.")).toBeVisible();
    section = programmeSection(page);
    await expect(section.getByText("Status correction pending")).toBeVisible();
    await expect(section.getByRole("button", { name: "Review" })).toHaveCount(0);

    await signOut(page);
    await login(page, USERS.admin);
    await page.goto(app(`/app/students/${requestedStudent}`));
    await page.getByRole("tab", { name: "Academic", exact: true }).click();
    section = programmeSection(page);
    await expect(section.getByText("Status correction pending")).toBeVisible();
    await section.getByRole("button", { name: "Review" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Review status correction request")).toBeVisible();
    await dialog.getByLabel("Decision reason").fill("E2E administrator approval");
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText("Status correction approved.")).toBeVisible();
    section = programmeSection(page);
    await expect(section.getByText("Active", { exact: true }).first()).toBeVisible();

    const requestedAdmissions = (await expectOk(
      await page.request.get(
        `${API_BASE}/api/v1/students/${requestedStudent}/admissions`,
      ),
      200,
    )) as { items: { status: string }[] };
    expect(requestedAdmissions.items[0].status).toBe("ACTIVE");
  });
});