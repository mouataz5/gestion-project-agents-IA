import { expect, test } from "@playwright/test";

test.describe("jobs and company watchlist (read-only)", () => {
  test("jobs and companies pages are enabled in the navigation", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    const navigation = page.getByRole("navigation", { name: "Main" });

    await navigation.getByRole("link", { name: "Jobs" }).click();

    await expect(page).toHaveURL(/\/jobs$/);
    await expect(
      page.getByRole("heading", { name: "Jobs", exact: true }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Last 24 h" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await navigation.getByRole("link", { name: "Companies" }).click();
    await expect(
      page.getByRole("heading", { name: "Company watchlist" }),
    ).toBeVisible();
  });

  test("sources show their policy: LinkedIn is manual only", async ({
    page,
  }) => {
    await page.goto("/jobs");

    const linkedin = page
      .getByTestId("source-row")
      .filter({ hasText: "linkedin" });
    await expect(linkedin).toContainText("Manual import only");
    await expect(linkedin).toContainText("Never scraped");
    const mockAts = page
      .getByTestId("source-row")
      .filter({ hasText: "mock_ats" });
    await expect(mockAts).toContainText("Yes");
  });

  test("unsafe job URLs are rejected before anything is stored", async ({
    page,
  }) => {
    await page.goto("/jobs");
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Import a job URL" }).click();
    const dialog = page.getByRole("dialog", { name: "Import a job URL" });
    await dialog
      .getByLabel("Job URL", { exact: true })
      .fill("http://127.0.0.1:8000/admin");
    await dialog.getByRole("button", { name: "Import job" }).click();

    await expect(dialog.getByRole("alert")).toContainText(
      "only public http(s) job pages",
    );
    await expect(page).toHaveURL(/\/jobs$/);
  });
});

test.describe("job discovery workflow (changes data)", () => {
  test.skip(
    !process.env.E2E_ALLOW_MUTATIONS,
    "Set E2E_ALLOW_MUTATIONS=1 to run tests that import companies, run discoveries and import jobs",
  );
  test.describe.configure({ mode: "serial" });

  test("import the watchlist seed, run a discovery and browse the jobs", async ({
    page,
  }) => {
    await page.goto("/companies");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Import companies.yaml" }).click();
    await expect(page.getByText("companies.yaml imported")).toBeVisible();
    await expect(
      page.getByTestId("company-row").filter({ hasText: "Nova AI" }),
    ).toBeVisible();

    await page.goto("/jobs");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Run job discovery" }).click();

    await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("run-status")).toContainText("Succeeded");
    const events = page.getByTestId("run-events");
    await expect(events).toContainText("discovery.source.mock_ats");
    await expect(events).toContainText("discovery.summary");

    await page.goto("/jobs");
    const rows = page.getByTestId("job-row");
    await expect(rows.filter({ hasText: "Senior AI Engineer" })).toContainText(
      "Posted 5 h ago",
    );
    await expect(
      rows.filter({ hasText: "Generative AI Engineer" }),
    ).toContainText("(estimated)");
    await expect(rows.filter({ hasText: "Account Executive" })).toHaveCount(0);

    await page.getByRole("link", { name: "Date unknown" }).click();
    await expect(page).toHaveURL(/tab=unknown/);
    await expect(rows.filter({ hasText: "Polaris Systems" })).toContainText(
      "Date unknown",
    );
  });

  test("filters narrow the list", async ({ page }) => {
    await page.goto("/jobs?tab=all");

    await page.getByLabel("Country").fill("DE");
    await page.getByRole("button", { name: "Apply" }).click();

    await expect(page).toHaveURL(/country=DE/);
    const rows = page.getByTestId("job-row");
    await expect(rows.first()).toBeVisible();
    for (const location of await rows
      .locator("td:nth-child(2)")
      .allInnerTexts()) {
      expect(location).toContain("Germany");
    }
  });

  test("a job shows its other listings, and an unknown-date job can be tracked", async ({
    page,
  }) => {
    await page.goto("/jobs?tab=all&q=Senior+AI+Engineer");
    await page
      .getByRole("link", { name: "Senior AI Engineer" })
      .first()
      .click();

    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("duplicate-listings")).toContainText(
      "mock_feed",
    );
    await expect(page.getByTestId("window-status")).toContainText(
      "In the last 24 h",
    );

    await page.goto("/jobs?tab=unknown");
    await page
      .getByTestId("job-row")
      .filter({ hasText: "Polaris Systems" })
      .getByRole("link")
      .click();
    await page.waitForLoadState("networkidle");
    const track = page.getByRole("button", { name: "Track this job" });
    if (await track.isVisible()) await track.click(); // already tracked when re-run locally
    await expect(
      page.getByRole("button", { name: "Track this job" }),
    ).toHaveCount(0);
    await expect(page.getByText("Discovered").first()).toBeVisible();
  });

  test("a pasted LinkedIn URL is imported without being fetched", async ({
    page,
  }) => {
    await page.goto("/jobs");
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Import a job URL" }).click();
    const dialog = page.getByRole("dialog", { name: "Import a job URL" });
    await dialog
      .getByLabel("Job URL", { exact: true })
      .fill("https://www.linkedin.com/jobs/view/4012345678/?trk=e2e");
    await dialog.getByLabel("Title", { exact: true }).fill("LLM Engineer");
    await dialog.getByLabel("Company", { exact: true }).fill("Vega Systems");
    await dialog.getByLabel("Posted", { exact: true }).fill("2 hours ago");
    await dialog.getByRole("button", { name: "Import job" }).click();

    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}\?imported=/);
    await expect(
      page.getByRole("heading", { name: "LLM Engineer" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Open posting on linkedin\.com/ }),
    ).toHaveAttribute("rel", "noopener noreferrer");
    await expect(page.getByText("(estimated)").first()).toBeVisible();
  });

  test("a watchlist company can be edited", async ({ page }) => {
    await page.goto("/companies");
    await page.waitForLoadState("networkidle");

    await page
      .getByTestId("company-row")
      .filter({ hasText: "Quiet Corp" })
      .getByRole("button", { name: "Edit" })
      .click();
    const dialog = page.getByRole("dialog", { name: "Edit Quiet Corp" });
    await dialog
      .getByLabel("Notes", { exact: true })
      .fill("Disabled example (edited by E2E)");
    await dialog.getByRole("button", { name: "Save changes" }).click();

    await expect(page.getByText("Quiet Corp updated.")).toBeVisible();
    await expect(dialog).toHaveCount(0);
  });
});
