import { expect, test, type Page } from "@playwright/test";

import { API_BASE, USERS, app } from "./accounts";

/**
 * Operational closure workflows.
 *
 * The seeded student has no immigration profile, so the test creates that
 * fixture through the authenticated API first; every institutional decision
 * afterwards (student submission, unauthorized verification state, approval,
 * document upload and replacement) is exercised through the browser UI.
 */

test.describe.configure({ mode: "serial" });
test.setTimeout(90_000);

function trackPageHealth(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(`pageerror: ${error.message}`));
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText?.includes("ERR_ABORTED")) return;
    failures.push(`requestfailed: ${request.method()} ${request.url()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 500) {
      failures.push(`http ${response.status()}: ${response.url()}`);
    }
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
  await page.waitForURL(new RegExp(`/en/login`), { timeout: 25_000 });
}

async function openSeededStudent(page: Page) {
  await page.goto(app("/app/students"));
  const filtered = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().includes("/api/v1/students") &&
      response.url().includes("search=STU-001"),
  );
  await page.getByRole("searchbox", { name: "Search" }).fill("STU-001");
  await filtered;

  const row = page.getByRole("row").filter({ hasText: "STU-001" }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await row.getByRole("link", { name: "View" }).click();
  await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
  return page.url();
}

async function openImmigrationTab(page: Page) {
  await page.getByRole("tab", { name: "Immigration" }).click();
}

async function findSeededStudentId(page: Page) {
  const response = await page.request.get(
    `${API_BASE}/api/v1/students?search=STU-001&page_size=5`,
  );
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as {
    items: { id: string; student_id: string }[];
  };
  const student = body.items.find((item) => item.student_id === "STU-001");
  expect(student).toBeTruthy();
  return student!.id;
}

const pdf = Buffer.from(
  [
    "%PDF-1.4",
    "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
    "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj",
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj",
    "trailer<</Root 1 0 R/Size 4>>",
    "%%EOF",
  ].join("\n"),
);

test("student renewal remains unverified until management approval", async ({
  page,
}) => {
  const failures = trackPageHealth(page);
  await login(page, USERS.admin);
  const studentId = await findSeededStudentId(page);

  const profileResponse = await page.request.get(
    `${API_BASE}/api/v1/students/${studentId}/immigration`,
  );
  expect(profileResponse.ok()).toBeTruthy();
  const profile = (await profileResponse.json()) as {
    passport_number: string | null;
    visa_type: string | null;
  };

  // Import is deliberately non-verifying. Applying an already-known value
  // returns the seeded profile to UNVERIFIED without inventing new data.
  const imported = await page.request.post(
    `${API_BASE}/api/v1/immigration/import/apply`,
    {
      data: {
        source_reference: "closure-test-fixture",
        records: [
          {
            student_id: studentId,
            values: { visa_type: profile.visa_type ?? "STUDENT" },
          },
        ],
        confirm: true,
      },
    },
  );
  expect(imported.ok()).toBeTruthy();

  await signOut(page);
  await login(page, USERS.student);
  await page.goto(app("/app/profile"));
  await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
  const profileUrl = page.url();
  await openImmigrationTab(page);
  await expect(page.getByText("Unverified", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Submit a change" }).click();
  const form = page.getByRole("dialog");
  await form.locator("select").selectOption("VISA");
  await form.getByLabel("Expiry date").fill("2031-01-01");
  await form.getByRole("button", { name: "Submit a change" }).click();
  await expect(
    page.getByText("Your request has been submitted for review."),
  ).toBeVisible({ timeout: 25_000 });

  await signOut(page);
  await login(page, USERS.admin);
  await page.goto(profileUrl);
  await openImmigrationTab(page);
  // A student submission is not a verification decision.
  await expect(page.getByText("Unverified", { exact: true })).toBeVisible();

  await page.goto(app("/app/immigration"));
  const request = page
    .getByRole("listitem")
    .filter({ hasText: "Student User" })
    .filter({ hasText: "Approve request" })
    .first();
  await expect(request).toBeVisible({ timeout: 25_000 });
  await request.getByRole("button", { name: "Approve request" }).click();
  const confirmation = page.getByRole("dialog");
  await confirmation.getByRole("button", { name: "Approve request" }).click();
  await expect(
    page.getByText("The change request has been approved and the record updated."),
  ).toBeVisible({ timeout: 25_000 });

  await page.goto(profileUrl);
  await openImmigrationTab(page);
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();
  await expect(page.getByText("Jan 1, 2031")).toBeVisible();
  expect(failures).toEqual([]);
});

test("admin uploads and replaces a document without losing the version", async ({
  page,
}) => {
  const failures = trackPageHealth(page);
  const stamp = Date.now().toString().slice(-7);
  const title = `E2E Closure Document ${stamp}`;

  await login(page, USERS.admin);
  await openSeededStudent(page);
  await page.getByRole("tab", { name: "Documents" }).click();
  await page.getByRole("button", { name: "Upload document" }).first().click();

  const upload = page.getByRole("dialog");
  await upload.locator('input[type="file"]').setInputFiles({
    name: `closure-${stamp}.pdf`,
    mimeType: "application/pdf",
    buffer: pdf,
  });
  await upload.getByLabel("Document type").selectOption("OTHER");
  await upload.locator("#document-title").fill(title);
  await expect(
    upload.getByRole("button", { name: "Upload", exact: true }),
  ).toBeEnabled();
  await upload.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText("The document has been uploaded.")).toBeVisible({
    timeout: 25_000,
  });
  await upload.getByRole("button", { name: "Cancel" }).click();

  const row = page.getByRole("listitem").filter({ hasText: title }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await row.getByRole("button", { name: "Replace" }).click();

  const replace = page.getByRole("dialog");
  await replace.locator('input[type="file"]').setInputFiles({
    name: `closure-${stamp}-v2.pdf`,
    mimeType: "application/pdf",
    buffer: pdf,
  });
  await replace.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(page.getByText("The new version has been uploaded.")).toBeVisible({
    timeout: 25_000,
  });
  await expect(row).toBeVisible();

  // The row action uses the same authorization-checked preview endpoint as
  // the profile's documents tab. A PDF is fetched as a private blob, not a
  // public URL.
  await row.getByRole("button", { name: "Preview" }).first().click();
  await expect(page.getByRole("dialog").getByText(`Preview: ${title}`)).toBeVisible({
    timeout: 25_000,
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close" })
    .first()
    .click();

  // The global documents page must expose the same preview action, not only
  // the profile's documents tab.
  await page.goto(app("/app/documents"));
  const globalRow = page.getByRole("row").filter({ hasText: title }).first();
  await expect(globalRow).toBeVisible({ timeout: 25_000 });
  await globalRow.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByRole("dialog").getByText(`Preview: ${title}`)).toBeVisible({
    timeout: 25_000,
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close" })
    .first()
    .click();
  expect(failures).toEqual([]);
});

test("admin onboards a student into a mapped intake offering", async ({ page }) => {
  const failures = trackPageHealth(page);
  const stamp = Date.now().toString().slice(-7);
  const number = `OI-${stamp}`;
  const offeringName = `Mapped offering ${stamp}`;

  await login(page, USERS.admin);
  const periodResponse = await page.request.post(
    `${API_BASE}/api/v1/academics/periods`,
    {
      data: {
        name: `Intake ${stamp}`,
        code: `IN-${stamp}`,
        start_date: "2035-09-01",
        end_date: "2035-12-20",
        status: "ACTIVE",
      },
    },
  );
  expect(periodResponse.status()).toBe(201);
  const period = (await periodResponse.json()) as { id: string };
  const programs = await page.request.get(`${API_BASE}/api/v1/academics/programs`);
  const program = ((await programs.json()) as { items: { id: string }[] }).items[0];
  const offeringResponse = await page.request.post(
    `${API_BASE}/api/v1/academics/program-offerings`,
    {
      data: {
        academic_period_id: period.id,
        source_id: `offer-${stamp}`,
        name: offeringName,
        program_id: program.id,
      },
    },
  );
  expect(offeringResponse.status()).toBe(201);
  const offering = (await offeringResponse.json()) as { id: string };

  await page.goto(app("/app/students"));
  await page.getByRole("button", { name: /add student/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/student number/i).fill(number);
  await dialog.getByLabel(/first name/i).fill("Offering");
  await dialog.getByLabel(/last name/i).fill(`Intake${stamp}`);
  await dialog.getByLabel(/^email/i).fill(`offering-${stamp}@example.com`);

  await dialog.getByLabel("Intake period").selectOption(period.id);
  const offeringSelect = dialog.getByLabel("Program offering");
  await expect(offeringSelect.locator("option")).not.toHaveCount(1);
  await offeringSelect.selectOption(offering.id);
  await dialog.getByRole("button", { name: /^create$/i }).click();
  await expect(page.getByTestId("temporary-password")).toBeVisible({
    timeout: 25_000,
  });
  await page.getByRole("button", { name: /done/i }).click();

  await page.getByRole("searchbox", { name: "Search" }).fill(number);
  const row = page.getByRole("row").filter({ hasText: number }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await row.getByRole("link", { name: "View" }).click();
  await page.waitForURL(/\/app\/students\/[0-9a-f-]+$/, { timeout: 25_000 });
  await page.getByRole("tab", { name: "Academic" }).click();
  await expect(page.getByText(offeringName).first()).toBeVisible({
    timeout: 25_000,
  });
  expect(failures).toEqual([]);
});

test("student previews their own uploaded PDF in the document library", async ({
  page,
}) => {
  const failures = trackPageHealth(page);
  const title = `Student preview ${Date.now().toString().slice(-7)}`;

  await login(page, USERS.student);
  const upload = await page.request.post(`${API_BASE}/api/v1/documents`, {
    multipart: {
      file: {
        name: "student-preview.pdf",
        mimeType: "application/pdf",
        buffer: pdf,
      },
      document_type: "OTHER",
      title,
    },
  });
  expect(upload.status()).toBe(201);

  await page.goto(app("/app/documents"));
  const row = page.getByRole("row").filter({ hasText: title }).first();
  await expect(row).toBeVisible({ timeout: 25_000 });
  await row
    .getByRole("button", { name: "Preview", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog").getByText(`Preview: ${title}`)).toBeVisible({
    timeout: 25_000,
  });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close" })
    .first()
    .click();
  expect(failures).toEqual([]);
});

test("admin previews and explicitly confirms a normalized import batch", async ({
  page,
}) => {
  const failures = trackPageHealth(page);
  await login(page, USERS.admin);
  const studentId = await findSeededStudentId(page);
  const profileResponse = await page.request.get(
    `${API_BASE}/api/v1/students/${studentId}/immigration`,
  );
  const profile = (await profileResponse.json()) as { visa_type: string | null };

  await page.goto(app("/app/immigration"));
  await page.getByRole("button", { name: "Import records" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Source reference").fill("e2e-ui-import");
  await dialog
    .getByLabel("Normalized batch")
    .fill(
      JSON.stringify([
        {
          student_id: studentId,
          values: { visa_type: profile.visa_type ?? "STUDENT" },
        },
      ]),
    );
  await dialog.getByRole("button", { name: "Preview batch" }).click();
  await expect(dialog.getByText("1 records previewed")).toBeVisible({
    timeout: 25_000,
  });
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Apply confirmed batch" }).click();
  await expect(page.getByText(/Import applied/)).toBeVisible({ timeout: 25_000 });
  expect(failures).toEqual([]);
});
