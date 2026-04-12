/**
 * E2E tests: Pause job action.
 *
 * Covers pause button visibility and API call for running jobs.
 */

import { test, expect } from "@playwright/test";
import { makeJob, setupJobDetailMocks } from "./helpers";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Pause Running Job", () => {
  test("pause button is visible for running jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "running" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // The pause button should be visible (titled "Pause agent")
    await expect(page.getByRole("button", { name: "Pause agent" })).toBeVisible();
  });

  test("pause button is hidden for completed jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "completed" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Pause button should not exist for completed jobs
    await expect(page.getByRole("button", { name: "Pause agent" })).not.toBeVisible();
  });

  test("pause button is hidden for failed jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "failed", failureReason: "Test failure" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Pause button should not exist for failed jobs
    await expect(page.getByRole("button", { name: "Pause agent" })).not.toBeVisible();
  });

  test("clicking pause calls POST /api/jobs/job-1/pause", async ({ page }) => {
    let pauseCalled = false;
    await setupJobDetailMocks(page, makeJob({ state: "running" }));

    await page.route("**/api/jobs/job-1/pause", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      pauseCalled = true;
      await route.fulfill({ status: 204 });
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Click pause
    await page.getByRole("button", { name: "Pause agent" }).click();

    // Verify API was called
    expect(pauseCalled).toBe(true);
  });
});
