import path from "node:path";

import { expect, test } from "@playwright/test";

// Fictional CV ("Alex Example"), regenerated with `uv run python scripts/generate_sample_cv.py`.
const SAMPLE_CV = path.resolve(__dirname, "../../fixtures/sample-cv.docx");

test.describe("candidate profile and master CV (read-only)", () => {
  test("candidate and CV pages are enabled in the navigation", async ({ page }) => {
    await page.goto("/dashboard");
    const navigation = page.getByRole("navigation", { name: "Main" });

    await navigation.getByRole("link", { name: "Candidate" }).click();

    await expect(page).toHaveURL(/\/candidate$/);
    await expect(page.getByRole("heading", { name: "Candidate profile" })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "CV", exact: true })).toBeVisible();
  });

  test("the profile is loaded and missing values are flagged, never guessed", async ({
    page,
  }) => {
    await page.goto("/candidate");

    await expect(page.getByLabel("Full name")).not.toHaveValue("");
    await expect(page.getByText(/need(s)? your input/).first()).toBeVisible();
    await expect(page.locator('[data-needs-input="true"]').first()).toBeVisible();
    await expect(page.getByTestId("skill-evidence")).toBeVisible();
  });

  test("the CV page offers an upload and rejects unsupported files", async ({ page }) => {
    await page.goto("/cv");
    await expect(page.getByTestId("cv-dropzone")).toBeVisible();

    await page.setInputFiles("#cv-file", {
      name: "cv.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("plain text is not accepted"),
    });

    await expect(page.getByTestId("cv-dropzone").getByRole("alert")).toContainText(
      "Only .docx and .pdf files are accepted.",
    );
  });
});

test.describe("master CV workflow (changes data)", () => {
  test.skip(
    !process.env.E2E_ALLOW_MUTATIONS,
    "Set E2E_ALLOW_MUTATIONS=1 to run tests that upload a CV and edit the profile",
  );
  test.describe.configure({ mode: "serial" });

  test("upload, review, confirm, then see the skill evidence", async ({ page }) => {
    page.on("dialog", (dialog) => void dialog.accept());
    await page.goto("/cv");

    await page.setInputFiles("#cv-file", SAMPLE_CV);

    await expect(page).toHaveURL(/version=[0-9a-f-]{36}/);
    const editor = page.getByTestId("cv-editor");
    await expect(editor.getByLabel("Job title").first()).toHaveValue("Senior AI Engineer");
    await expect(editor.getByLabel("Employer").first()).toHaveValue("Acme Analytics");

    await editor.getByLabel("Summary").fill("AI engineer building LLM and RAG systems.");
    await page.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText("Draft saved.")).toBeVisible();

    await page.getByTestId("confirm-cv").click();

    const view = page.getByTestId("cv-view");
    await expect(view).toContainText("Senior AI Engineer");
    await expect(view).toContainText("AI engineer building LLM and RAG systems.");

    await page.goto("/candidate");
    const langgraph = page.locator('[data-skill="LangGraph"]');
    await expect(langgraph).toContainText("Demonstrated");
    await langgraph.locator("summary").click();
    await expect(langgraph).toContainText("LangGraph and a vector database");
    await expect(page.locator('[data-skill="Deep Learning"]')).toContainText("No evidence");
  });

  test("profile edits are saved", async ({ page }) => {
    await page.goto("/candidate");

    await page.getByLabel("Notice period").fill("1 month");
    await page.getByRole("button", { name: "Save profile" }).click();

    await expect(page.getByText("Profile saved.")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Notice period")).toHaveValue("1 month");
  });
});
