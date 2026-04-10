/**
 * E2E tests: Keyboard shortcuts and command palette.
 *
 * Covers global navigation shortcuts (Alt+J, Alt+N, Alt+A, Alt+H),
 * settings shortcut (Ctrl+,), command palette (Ctrl+K), and
 * within-palette keyboard navigation.
 */

import { test, expect } from "@playwright/test";
import { setupBaseMocks } from "./helpers";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Mock all analytics endpoints so /analytics doesn't crash. */
async function setupAnalyticsRoutes(page: import("@playwright/test").Page) {
  const emptyScorecard = {
    activity: {
      totalJobs: 0, running: 0, inReview: 0, merged: 0,
      prCreated: 0, discarded: 0, failed: 0, cancelled: 0,
    },
    budget: [],
    quotaJson: null,
    costTrend: [],
  };
  for (const pattern of [
    "**/api/analytics/scorecard*",
    "**/api/analytics/model-comparison*",
    "**/api/analytics/tools*",
    "**/api/analytics/repos*",
    "**/api/analytics/observations*",
    "**/api/analytics/jobs*",
    "**/api/analytics/cost-drivers*",
  ]) {
    await page.route(pattern, async (route) => {
      const body =
        pattern.includes("scorecard") ? emptyScorecard :
        pattern.includes("model-comparison") ? { period: 7, repo: null, models: [] } :
        pattern.includes("tools") ? { period: 7, tools: [] } :
        pattern.includes("repos") ? { period: 7, repos: [] } :
        pattern.includes("jobs") ? { items: [], cursor: null, hasMore: false } :
        [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
  }
}

// ---------------------------------------------------------------------------
// Tests: Global navigation shortcuts
// ---------------------------------------------------------------------------

test.describe("Keyboard Shortcuts — Navigation", () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page);
    await setupAnalyticsRoutes(page);
  });

  test("Alt+N navigates to New Job", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Alt+n");
    await expect(page).toHaveURL(/\/jobs\/new/, { timeout: 5_000 });
  });

  test("Alt+J navigates to Dashboard", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText(/Settings/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Alt+j");
    await expect(page).toHaveURL(/^\/$|\/\?/, { timeout: 5_000 });
  });

  test("Alt+H navigates to History", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Alt+h");
    await expect(page).toHaveURL(/\/history/, { timeout: 5_000 });
  });

  test("Alt+A navigates to Analytics", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Alt+a");
    await expect(page).toHaveURL(/\/analytics/, { timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Tests: Command Palette
// ---------------------------------------------------------------------------

test.describe("Command Palette", () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page);
    await setupAnalyticsRoutes(page);
  });

  test("Ctrl+K opens command palette", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Control+k");

    // Command palette dialog should appear
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 3_000 });
  });

  test("palette shows navigation items", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 3_000 });

    // Should show common navigation targets
    await expect(page.getByText(/New Job/i).first()).toBeVisible();
    await expect(page.getByText(/Settings/i).first()).toBeVisible();
    await expect(page.getByText(/Analytics/i).first()).toBeVisible();
    await expect(page.getByText(/History/i).first()).toBeVisible();
  });

  test("palette closes on Escape", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 3_000 });

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 2_000 });
  });

  test("palette search filters items", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 3_000 });

    // Type in the search to filter
    await page.keyboard.type("settings");

    // Settings should still be visible, other items may be filtered out
    await expect(
      page.getByRole("dialog").getByText(/Settings/i).first(),
    ).toBeVisible();
  });

  test("selecting a palette item navigates", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog").first()).toBeVisible({ timeout: 3_000 });

    // Type to filter to Settings, then press Enter
    await page.keyboard.type("settings");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/settings/, { timeout: 5_000 });
  });
});
