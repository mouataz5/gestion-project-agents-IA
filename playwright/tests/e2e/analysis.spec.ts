import { expect, test } from "@playwright/test";

// Runs after the other specs (see playwright.config.ts): with E2E_ALLOW_MUTATIONS, they confirm the
// sample CV and discover the mock jobs this workflow analyses.

test.describe("job analysis (read-only)", () => {
  test("the dashboard summarises the analysis and names the engine", async ({
    page,
  }) => {
    await page.goto("/dashboard");

    const summary = page.getByTestId("analysis-summary");
    for (const label of ["Apply", "Review", "Skip", "Waiting for analysis"]) {
      await expect(summary).toContainText(label);
    }
    await expect(page.getByTestId("analysis-engine")).toContainText(
      /Claude|Offline mock|Unavailable/,
    );
    await expect(
      page.getByRole("button", { name: "Analyse new jobs" }),
    ).toBeVisible();
  });

  test("settings show the language model, never the key", async ({ page }) => {
    await page.goto("/settings");

    await expect(
      page.getByRole("heading", { name: "Language model" }),
    ).toBeVisible();
    await expect(page.getByTestId("llm-effective")).toBeVisible();
    await expect(page.getByText("LLM_REFUSAL_FALLBACK")).toBeVisible();
    await expect(page.getByText(/sk-ant-/)).toHaveCount(0);
  });

  test("jobs can be filtered by recommendation and visa status", async ({
    page,
  }) => {
    await page.goto("/jobs?tab=all");

    await page.getByLabel("Recommendation").selectOption("APPLY");
    await page.getByLabel("Visa").selectOption("SPONSORSHIP_CONFIRMED");
    await page.getByRole("button", { name: "Apply", exact: true }).click();

    await expect(page).toHaveURL(/recommendation=APPLY/);
    await expect(page).toHaveURL(/visa=SPONSORSHIP_CONFIRMED/);
    for (const row of await page.getByTestId("job-row").all()) {
      await expect(row.getByTestId("recommendation")).toHaveText("Apply");
      await expect(row.getByTestId("visa-status")).toHaveText(
        "Sponsorship confirmed",
      );
    }
  });
});

test.describe("job analysis workflow (changes data)", () => {
  test.skip(
    !process.env.E2E_ALLOW_MUTATIONS,
    "Set E2E_ALLOW_MUTATIONS=1 to run tests that analyse jobs",
  );
  test.describe.configure({ mode: "serial" });

  test("analyse the new jobs, then read why a job is worth applying to", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Analyse new jobs" }).click();

    await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("run-status")).toContainText("Succeeded");
    await expect(page.getByTestId("run-events")).toContainText(
      "analysis.summary",
    );

    await page.goto("/jobs?tab=all&recommendation=APPLY");
    await page
      .getByTestId("job-row")
      .filter({ hasText: "Nova AI" })
      .getByRole("link", { name: "Senior AI Engineer" })
      .click();

    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    const analysis = page.getByTestId("job-analysis");
    await expect(analysis.getByTestId("recommendation")).toHaveText("Apply");
    await expect(
      analysis.getByText("Mock analysis", { exact: true }),
    ).toBeVisible();
    await expect(analysis.getByTestId("analysis-reasons")).toContainText(
      "Visa sponsorship is confirmed by the posting.",
    );
    await expect(analysis.getByTestId("visa-quote").first()).toContainText(
      "Visa sponsorship is available for non-EU candidates.",
    );
    await expect(analysis.getByTestId("skill-coverage")).toContainText(
      "required skills backed by your CV",
    );
    await expect(
      page.getByTestId("job-description").locator("mark").first(),
    ).toContainText("Visa sponsorship is available");
  });

  test("a posting that rules out sponsorship is skipped, with the quote", async ({
    page,
  }) => {
    await page.goto("/jobs?tab=all&visa=SPONSORSHIP_NOT_AVAILABLE");
    await page
      .getByRole("link", { name: "Data Scientist, Time Series" })
      .click();

    const analysis = page.getByTestId("job-analysis");
    await expect(analysis.getByTestId("recommendation")).toHaveText("Skip");
    await expect(analysis.getByTestId("analysis-reasons")).toContainText(
      "rules out visa sponsorship",
    );
    await expect(analysis.getByTestId("visa-quote").first()).toContainText(
      "unable to offer visa sponsorship",
    );
  });

  test("a job can be re-analysed from its page", async ({ page }) => {
    await page.goto("/jobs?tab=all&recommendation=APPLY");
    await page.getByRole("link", { name: "AI Research Engineer" }).click();
    await page.waitForLoadState("networkidle");
    const provenance = page.getByTestId("analysis-provenance");
    const before = await provenance.innerText();

    await page.getByRole("button", { name: "Re-analyse" }).click();

    await expect(
      page.getByRole("button", { name: "Analysing…" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-analyse" })).toBeVisible({
      timeout: 60_000,
    });
    await expect(provenance).not.toHaveText(before);
    await expect(page.getByTestId("recommendation")).toHaveText("Apply");
  });
});
