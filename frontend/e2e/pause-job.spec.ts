/**
 * E2E tests: Pause job action.
 *
 * Covers cancel button visibility and API call for running jobs.
 */

import { test, expect } from "@playwright/test";
import { makeJob, setupJobDetailMocks } from "./helpers";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Pause Running Job", () => {
  test("cancel button is visible for running jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "running" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).last()).toBeVisible({ timeout: 5_000 });

    // The cancel button should be visible for running jobs
    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
  });

  test("cancel button is hidden for completed jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "completed" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).last()).toBeVisible({ timeout: 5_000 });

    // Cancel button should not exist for completed jobs
    await expect(page.getByRole("button", { name: "Cancel" })).not.toBeVisible();
  });

  test("cancel button is hidden for failed jobs", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob({ state: "failed", failureReason: "Test failure" }));

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).last()).toBeVisible({ timeout: 5_000 });

    // Cancel button should not exist for failed jobs
    await expect(page.getByRole("button", { name: "Cancel" })).not.toBeVisible();
  });

  test("clicking cancel calls POST /api/jobs/job-1/cancel", async ({ page }) => {
    let cancelCalled = false;
    await setupJobDetailMocks(page, makeJob({ state: "running" }));

    await page.route("**/api/jobs/job-1/cancel", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      cancelCalled = true;
      await route.fulfill({ status: 204 });
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).last()).toBeVisible({ timeout: 5_000 });

    // Open the confirmation dialog, then confirm the cancel action.
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog", { name: "Cancel & Clean Up?" })).toBeVisible();
    await page.getByRole("button", { name: "Cancel & Clean Up" }).click();

    // Verify API was called
    expect(cancelCalled).toBe(true);
  });
});
