import { expect, test } from "@playwright/test";

test.describe("dashboard foundation", () => {
  test("shows the safety state and healthy components", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByTestId("mock-mode-badge")).toContainText("MOCK MODE");
    await expect(page.getByText("Auto-submit OFF")).toBeVisible();

    for (const component of ["database", "migrations", "redis", "storage", "worker"]) {
      await expect(page.getByTestId(`health-${component}`)).toContainText("Ok");
    }
  });

  test("runs a system diagnostic end to end", async ({ page }) => {
    await page.goto("/dashboard");

    await page.getByRole("button", { name: "Run system diagnostic" }).click();

    await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("run-status")).toContainText("Succeeded");
    const events = page.getByTestId("run-events");
    for (const stage of ["database", "migrations", "redis", "storage"]) {
      await expect(events).toContainText(`diagnostic.${stage}`);
    }
  });

  test("lists runs and filters them by status", async ({ page }) => {
    await page.goto("/runs");
    await expect(page.getByTestId("run-row").first()).toBeVisible();

    await page.getByRole("link", { name: "Succeeded", exact: true }).click();

    await expect(page).toHaveURL(/status=SUCCEEDED/);
    await expect(page.getByTestId("run-row").first()).toContainText("Succeeded");
  });

  test("shows later-phase pages as disabled", async ({ page }) => {
    await page.goto("/dashboard");
    const navigation = page.getByRole("navigation", { name: "Main" });

    await expect(navigation.getByRole("link", { name: "Runs" })).toBeVisible();
    const jobs = navigation.locator('[aria-disabled="true"]', { hasText: "Jobs" });
    await expect(jobs).toContainText("Phase 3");
  });

  test("settings report secrets without revealing them", async ({ page }) => {
    await page.goto("/settings");

    const secrets = page.getByTestId("secrets-status");
    await expect(secrets).toContainText("API_AUTH_TOKEN");
    await expect(secrets).toContainText("configured");
    const token = process.env.API_AUTH_TOKEN;
    if (token) {
      expect(await page.content()).not.toContain(token);
    }
  });
});
