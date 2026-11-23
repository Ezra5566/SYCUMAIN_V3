import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration.
 *
 * The supported entry point is `./scripts/e2e.sh`, which brings up
 * `docker-compose.test.yml`: a disposable database and its own api/web on
 * 8001/3001, seeded deterministically, torn down afterwards. The suite still
 * runs against real containers, so it validates the artifact operators deploy.
 *
 * The config does not start servers itself. Override an existing isolated
 * target with E2E_BASE_URL / E2E_API_URL; the defaults name the test stack so a
 * stray run cannot silently target the development one.
 */
export default defineConfig({
  testDir: "./e2e",
  // Retires the students the lifecycle tests onboard. With the isolated stack
  // the database is discarded anyway, but this keeps a developer's ad-hoc run
  // against a reused database from leaving accounts behind.
  globalTeardown: "./e2e/global-teardown.ts",
  outputDir: "./test-results",
  // The visual-review spec only runs via `pnpm screenshots`.
  testIgnore: process.env.VISUAL ? [] : ["**/visual.spec.ts"],
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["list"]],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3001",
    // Defaults to Playwright's bundled Chromium. E2E_CHANNEL=chrome runs the
    // same specs against a locally installed Chrome, which is the fallback on a
    // machine where the browser download is unavailable.
    channel: process.env.E2E_CHANNEL || undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
