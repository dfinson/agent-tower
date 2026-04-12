/**
 * E2E tests: Job Creation form validation.
 *
 * Covers prompt validation, form field rendering,
 * permission mode selection, and submission behavior.
 */

import { test, expect } from "@playwright/test";
import { setupBaseMocks } from "./helpers";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Job Creation — Form Rendering", () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page);

    // Mock repo detail for base ref auto-detection
    await page.route("**/api/settings/repos/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          path: "/tmp/test-repo",
          defaultBranch: "main",
          currentBranch: "main",
        }),
      });
    });

    // Mock suggest-names endpoint
    await page.route("**/api/jobs/suggest-names*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          branchName: "fix-auth-bug",
          title: "Fix Auth Bug",
          worktreeName: "fix-auth-bug",
        }),
      });
    });

    // Mock model comparison
    await page.route("**/analytics/model-comparison*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ models: [] }),
      });
    });
  });

  test("shows prompt input and create button", async ({ page }) => {
    await page.goto("/jobs/new");

    // Prompt textarea should be visible
    const textarea = page.locator("textarea").first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });

    // Create Job button should exist
    await expect(page.locator("button", { hasText: "Create Job" })).toBeVisible();
  });

  test("shows permission mode radio buttons", async ({ page }) => {
    await page.goto("/jobs/new");

    await expect(page.locator("textarea").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Permission Mode")).toBeVisible();
  });

  test("shows repository selector with options", async ({ page }) => {
    await page.goto("/jobs/new");

    await expect(page.locator("textarea").first()).toBeVisible({ timeout: 5_000 });

    // Repository combobox should show the test repo
    await expect(page.getByText("test-repo").first()).toBeVisible();
  });
});

test.describe("Job Creation — Validation", () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page);

    await page.route("**/api/settings/repos/*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          path: "/tmp/test-repo",
          defaultBranch: "main",
          currentBranch: "main",
        }),
      });
    });

    await page.route("**/api/jobs/suggest-names*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          branchName: "fix-auth",
          title: "Fix Auth",
          worktreeName: "fix-auth",
        }),
      });
    });

    await page.route("**/analytics/model-comparison*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ models: [] }),
      });
    });
  });

  test("shows validation error when prompt is empty on blur", async ({ page }) => {
    await page.goto("/jobs/new");

    const textarea = page.locator("textarea").first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });

    // Focus and then blur without typing
    await textarea.focus();
    await textarea.blur();

    // Validation error message should appear
    await expect(page.getByText("A prompt is required")).toBeVisible({ timeout: 3_000 });
  });

  test("clears validation error when prompt is filled", async ({ page }) => {
    await page.goto("/jobs/new");

    const textarea = page.locator("textarea").first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });

    // Trigger validation error
    await textarea.focus();
    await textarea.blur();
    await expect(page.getByText("A prompt is required")).toBeVisible({ timeout: 3_000 });

    // Fill in prompt and blur again
    await textarea.fill("Fix the authentication bug");
    await textarea.blur();

    // Error should be gone
    await expect(page.getByText("A prompt is required")).not.toBeVisible({ timeout: 3_000 });
  });

  test("create button is disabled when submitting", async ({ page }) => {
    let resolveCreate: (() => void) | undefined;
    const createPromise = new Promise<void>((resolve) => { resolveCreate = resolve; });

    await page.route("**/api/jobs", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      // Hold the request to observe loading state
      await createPromise;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ id: "job-1" }),
      });
    });

    // Mock job detail redirect targets
    await page.route("**/api/jobs/job-1", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "job-1", state: "queued", title: "Fix Auth", prompt: "Fix auth", createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), repo: "/tmp/test-repo", branch: "cpl/job-1", baseRef: "main", sdk: "copilot" }) });
    });
    await page.route("**/api/jobs/job-1/snapshot*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job: { id: "job-1", state: "queued", title: "Fix Auth", prompt: "Fix auth", createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), repo: "/tmp/test-repo", branch: "cpl/job-1", baseRef: "main", sdk: "copilot" }, logs: [], transcript: [], diff: [], approvals: [], timeline: [] }) });
    });
    await page.route("**/api/jobs/job-1/transcript*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/job-1/approvals*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto("/jobs/new");

    const textarea = page.locator("textarea").first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });
    await textarea.fill("Fix the authentication bug");

    const createBtn = page.locator("button", { hasText: "Create Job" });
    await createBtn.click();

    // Release the held request
    resolveCreate!();

    // Should navigate to job detail
    await expect(page).toHaveURL(/\/jobs\/job-1/, { timeout: 10_000 });
  });
});
