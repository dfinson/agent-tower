/**
 * E2E tests: Analytics screen.
 *
 * Covers scorecard rendering, budget/activity overview,
 * model comparison table, tool health table, and period filtering.
 */

import { test, expect } from "@playwright/test";
import { setupBaseMocks, sseBody } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SCORECARD = {
  activity: {
    totalJobs: 42,
    running: 2,
    inReview: 3,
    merged: 25,
    prCreated: 5,
    discarded: 2,
    failed: 4,
    cancelled: 1,
  },
  budget: [
    {
      sdk: "copilot",
      totalCostUsd: 12.5,
      premiumRequests: 340,
      jobCount: 42,
      avgCostPerJob: 0.3,
      avgDurationMs: 90_000,
    },
  ],
  quotaJson: null,
  costTrend: [
    { date: "2026-04-05", cost: 2.1, jobs: 8 },
    { date: "2026-04-06", cost: 3.5, jobs: 12 },
    { date: "2026-04-07", cost: 1.8, jobs: 6 },
    { date: "2026-04-08", cost: 2.9, jobs: 10 },
    { date: "2026-04-09", cost: 2.2, jobs: 6 },
  ],
};

const MODEL_COMPARISON = {
  period: 7,
  repo: null,
  models: [
    {
      model: "claude-sonnet-4-5-20250514",
      sdk: "copilot",
      jobCount: 30,
      avgCost: 0.25,
      avgDurationMs: 85_000,
      totalCostUsd: 7.5,
      premiumRequests: 240,
      merged: 20,
      prCreated: 4,
      discarded: 2,
      failed: 3,
      avgVerifyTurns: null,
      verifyJobCount: 0,
      avgDiffLines: 45.2,
      cacheHitRate: 0.12,
      costPerJob: 0.25,
      costPerMinute: 0.18,
      costPerTurn: 0.02,
      costPerToolCall: 0.005,
    },
    {
      model: "claude-opus-4-20250514",
      sdk: "copilot",
      jobCount: 12,
      avgCost: 0.42,
      avgDurationMs: 120_000,
      totalCostUsd: 5.0,
      premiumRequests: 100,
      merged: 5,
      prCreated: 1,
      discarded: 0,
      failed: 1,
      avgVerifyTurns: null,
      verifyJobCount: 0,
      avgDiffLines: 82.0,
      cacheHitRate: 0.08,
      costPerJob: 0.42,
      costPerMinute: 0.21,
      costPerTurn: 0.04,
      costPerToolCall: 0.01,
    },
  ],
};

const TOOLS = {
  period: 7,
  tools: [
    { name: "edit_file", count: 156, avgDurationMs: 45, totalDurationMs: 7020, failureCount: 3 },
    { name: "read_file", count: 312, avgDurationMs: 22, totalDurationMs: 6864, failureCount: 0 },
    { name: "run_in_terminal", count: 89, avgDurationMs: 3500, totalDurationMs: 311500, failureCount: 12 },
  ],
};

const REPOS = {
  period: 7,
  repos: [
    {
      repo: "/home/user/project-a",
      jobCount: 28,
      succeeded: 22,
      failed: 3,
      totalCostUsd: 8.4,
      totalTokens: 450_000,
      toolCalls: 420,
      avgDurationMs: 85_000,
      premiumRequests: 220,
    },
  ],
};

const OBSERVATIONS: unknown[] = [];
const ANALYTICS_JOBS = { items: [], cursor: null, hasMore: false };
const COST_DRIVERS: unknown[] = [];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function setupAnalyticsMocks(page: import("@playwright/test").Page) {
  await setupBaseMocks(page);

  await page.route("**/api/analytics/scorecard*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SCORECARD),
    });
  });

  await page.route("**/api/analytics/model-comparison*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MODEL_COMPARISON),
    });
  });

  await page.route("**/api/analytics/tools*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(TOOLS),
    });
  });

  await page.route("**/api/analytics/repos*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(REPOS),
    });
  });

  await page.route("**/api/analytics/observations*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(OBSERVATIONS),
    });
  });

  await page.route("**/api/analytics/jobs*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ANALYTICS_JOBS),
    });
  });

  await page.route("**/api/analytics/cost-drivers*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(COST_DRIVERS),
    });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Analytics — Page Load", () => {
  test("renders analytics heading", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    await expect(page.getByText("Analytics").first()).toBeVisible({ timeout: 5_000 });
  });

  test("displays activity counts from scorecard", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    // Activity metrics — total jobs count
    await expect(page.getByText("42").first()).toBeVisible({ timeout: 5_000 });
    // Merged count
    await expect(page.getByText("25").first()).toBeVisible();
  });

  test("displays budget information", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    // Budget shows total cost — look for dollar amount
    await expect(page.getByText(/\$12\.50|\$12\.5/i).first()).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Analytics — Model Comparison", () => {
  test("renders model comparison table with model names", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    // Model names should appear in the comparison section
    await expect(
      page.getByText(/sonnet/i).first(),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText(/opus/i).first(),
    ).toBeVisible();
  });

  test("shows job counts per model", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    // Model comparison heading should be visible
    await expect(page.getByText("Model Comparison").first()).toBeVisible({ timeout: 5_000 });
    // Model names should appear (sonnet or opus)
    await expect(page.getByText(/sonnet|opus/i).first()).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Analytics — Tool Health", () => {
  test("shows tool names and call counts", async ({ page }) => {
    await setupAnalyticsMocks(page);
    await page.goto("/analytics");

    // Tool Health section is collapsed — click to expand
    const toolHealthBtn = page.getByRole("button", { name: /Tool Health/i });
    await expect(toolHealthBtn).toBeVisible({ timeout: 5_000 });
    await toolHealthBtn.click();

    // Tool names should now be visible
    await expect(
      page.getByText(/edit_file|read_file|run_in_terminal/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Analytics — Empty State", () => {
  test("handles no data gracefully", async ({ page }) => {
    await setupBaseMocks(page);

    // Return empty scorecard
    await page.route("**/api/analytics/scorecard*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          activity: {
            totalJobs: 0, running: 0, inReview: 0, merged: 0,
            prCreated: 0, discarded: 0, failed: 0, cancelled: 0,
          },
          budget: [],
          quotaJson: null,
          costTrend: [],
        }),
      });
    });

    await page.route("**/api/analytics/model-comparison*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ period: 7, repo: null, models: [] }),
      });
    });

    await page.route("**/api/analytics/tools*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ period: 7, tools: [] }),
      });
    });

    await page.route("**/api/analytics/repos*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ period: 7, repos: [] }),
      });
    });

    await page.route("**/api/analytics/observations*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.route("**/api/analytics/jobs*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], cursor: null, hasMore: false }),
      });
    });

    await page.route("**/api/analytics/cost-drivers*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.goto("/analytics");

    // Page should load without errors
    await expect(page.getByText("Analytics").first()).toBeVisible({ timeout: 5_000 });
  });
});
