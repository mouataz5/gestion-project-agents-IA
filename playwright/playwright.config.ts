import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against an already running stack (`make up`, or backend + worker + frontend
 * started natively). Set E2E_BASE_URL to target another address.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "../.artifacts/playwright-results.json" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /(analysis|tailoring)\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    // The analysis needs what the other specs create (confirmed CV, discovered jobs): it runs
    // once they are done, whatever the number of workers.
    {
      name: "analysis",
      testMatch: /analysis\.spec\.ts/,
      dependencies: ["chromium"],
      use: { ...devices["Desktop Chrome"] },
    },
    // The tailoring needs analysed jobs (APPLY recommendations): it runs after the analysis.
    {
      name: "tailoring",
      testMatch: /tailoring\.spec\.ts/,
      dependencies: ["analysis"],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
