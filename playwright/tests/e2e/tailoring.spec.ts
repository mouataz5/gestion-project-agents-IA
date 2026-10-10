import { expect, test, type Page } from "@playwright/test";

// Runs after the analysis (see playwright.config.ts): with E2E_ALLOW_MUTATIONS, the confirmed sample
// CV and the analysed mock jobs are what this workflow tailors. The scores are the deterministic
// ats-score.v1 values of the sample CV against the Nova AI posting (backend golden tests).

async function openNovaJob(page: Page) {
  await page.goto("/jobs?tab=all&recommendation=APPLY");
  await page
    .getByTestId("job-row")
    .filter({ hasText: "Nova AI" })
    .getByRole("link", { name: "Senior AI Engineer" })
    .click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
  await page.waitForLoadState("networkidle");
}

test.describe("CV tailoring (read-only)", () => {
  test("the dashboard offers CV generation and calls the target a target", async ({
    page,
  }) => {
    await page.goto("/dashboard");

    const summary = page.getByTestId("cv-generation-summary");
    for (const label of ["Tailored CVs", "APPLY jobs waiting", "REVIEW jobs"]) {
      await expect(summary).toContainText(label);
    }
    await expect(summary).toContainText("a target, not a promise");
    await expect(
      page.getByRole("button", { name: "Tailor CVs" }),
    ).toBeVisible();
  });

  test("settings show the ATS engine and its score weights", async ({
    page,
  }) => {
    await page.goto("/settings");

    await expect(
      page.getByRole("heading", { name: "ATS engine" }),
    ).toBeVisible();
    await expect(page.getByText("ats-score.v1")).toBeVisible();
    const weights = page.getByTestId("ats-weights");
    await expect(weights).toContainText("Job keywords 30");
    await expect(weights).toContainText("ATS-friendly structure 5");
  });

  test("the CV page has a tailored CVs section", async ({ page }) => {
    await page.goto("/cv");

    await expect(
      page.getByRole("heading", { name: /^Tailored CVs \(\d+\)$/ }),
    ).toBeVisible();
  });
});

test.describe("CV tailoring workflow (changes data)", () => {
  test.skip(
    !process.env.E2E_ALLOW_MUTATIONS,
    "Set E2E_ALLOW_MUTATIONS=1 to run tests that tailor CVs",
  );
  test.describe.configure({ mode: "serial" });

  test("tailor the APPLY jobs, then read the ATS report of a job", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Tailor CVs" }).click();

    await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("run-status")).toContainText("Succeeded");
    await expect(page.getByTestId("run-events")).toContainText(
      "tailoring.summary",
    );

    await page.goto("/jobs?tab=all&recommendation=APPLY");
    await expect(
      page
        .getByTestId("job-row")
        .filter({ hasText: "Nova AI" })
        .getByTestId("ats-score"),
    ).toHaveText("ATS 88.3");

    await openNovaJob(page);
    const tailoring = page.getByTestId("tailoring");
    await expect(tailoring.getByTestId("ats-score-summary")).toHaveText(
      "ATS 82.3 → 88.3",
    );
    await expect(tailoring).toContainText("target 95");
    await expect(tailoring).toContainText("reachable with your master CV 88.3");
    await expect(tailoring.getByTestId("stop-reason")).toHaveText(
      "Only unsupported gains left",
    );
    await expect(
      tailoring.getByText("Mock tailoring", { exact: true }),
    ).toBeVisible();
    await expect(tailoring.getByTestId("unsupported-keywords")).toContainText(
      "0 unsupported keywords",
    );
    await expect(tailoring.getByTestId("ats-keywords")).toContainText(
      "LangGraph",
    );
    await expect(tailoring.getByTestId("ats-gaps")).toContainText(
      "Mentor engineers",
    );
  });

  test("the tailored CV shows where every text comes from", async ({
    page,
  }) => {
    await openNovaJob(page);
    await page.getByRole("link", { name: "Open the tailored CV →" }).click();

    await expect(page).toHaveURL(/\/cv\/tailored\/[0-9a-f-]{36}$/);
    await expect(
      page.getByRole("heading", { name: "Tailored CV · Senior AI Engineer" }),
    ).toBeVisible();
    // Employers and dates are copied from the master CV, never written by the tailoring.
    await expect(page.getByText("Acme Analytics, Paris, France")).toBeVisible();
    await expect(
      page
        .getByTestId("source-badge")
        .filter({ hasText: "Experience 1 · bullet 1" }),
    ).toBeVisible();
    await expect(page.getByTestId("skill-evidence")).toContainText("LangGraph");
    await expect(
      page.getByRole("heading", { name: "Rewrites reverted by the guard (0)" }),
    ).toBeVisible();

    await page.goto("/cv");
    await expect(page.getByTestId("tailored-cvs")).toContainText(
      "Senior AI Engineer",
    );
  });

  test("a job can be re-tailored from its page", async ({ page }) => {
    await openNovaJob(page);
    const open = page.getByRole("link", { name: "Open the tailored CV →" });
    const before = await open.getAttribute("href");

    await page.getByRole("button", { name: "Re-tailor" }).click();

    await expect(
      page.getByRole("button", { name: "Tailoring…" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-tailor" })).toBeVisible({
      timeout: 60_000,
    });
    await expect(open).not.toHaveAttribute("href", before ?? "");
    await expect(page.getByTestId("ats-score-summary")).toHaveText(
      "ATS 82.3 → 88.3",
    );
  });
});
