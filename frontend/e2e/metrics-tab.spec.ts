/**
 * E2E tests: Metrics Tab on Job Detail.
 *
 * Covers telemetry data display, stat cards, tool calls table,
 * empty/loading states, and cache efficiency rendering.
 */

import { test, expect } from "@playwright/test";
import { makeJob, setupJobDetailMocks } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TELEMETRY = {
  available: true,
  jobId: "job-1",
  sdk: "claude",
  model: "claude-sonnet-4-5-20250514",
  mainModel: "claude-sonnet-4-5-20250514",
  durationMs: 154_000,
  inputTokens: 45_200,
  outputTokens: 8_300,
  totalTokens: 53_500,
  cacheReadTokens: 12_000,
  cacheWriteTokens: 3_500,
  totalCost: 0.42,
  contextWindowSize: 200_000,
  currentContextTokens: 53_500,
  contextUtilization: 26.75,
  compactions: 0,
  tokensCompacted: 0,
  toolCallCount: 12,
  totalToolDurationMs: 5_600,
  toolCalls: [
    { name: "read_file", durationMs: 120, success: true },
    { name: "read_file", durationMs: 95, success: true },
    { name: "read_file", durationMs: 110, success: true },
    { name: "edit_file", durationMs: 45, success: true },
    { name: "edit_file", durationMs: 60, success: true },
    { name: "grep_search", durationMs: 200, success: true },
    { name: "grep_search", durationMs: 180, success: false },
    { name: "list_dir", durationMs: 30, success: true },
    { name: "run_in_terminal", durationMs: 2_500, success: true },
    { name: "run_in_terminal", durationMs: 1_800, success: true },
    { name: "semantic_search", durationMs: 350, success: true },
    { name: "file_search", durationMs: 110, success: true },
  ],
  llmCallCount: 6,
  totalLlmDurationMs: 12_000,
  llmCalls: [
    { model: "claude-sonnet-4-5-20250514", inputTokens: 10000, outputTokens: 2000, cacheReadTokens: 3000, cacheWriteTokens: 1000, cost: 0.08, durationMs: 2000, isSubagent: false },
    { model: "claude-sonnet-4-5-20250514", inputTokens: 12000, outputTokens: 1500, cacheReadTokens: 4000, cacheWriteTokens: 500, cost: 0.07, durationMs: 2200, isSubagent: false },
  ],
  approvalCount: 1,
  totalApprovalWaitMs: 15_000,
  agentMessages: 8,
  operatorMessages: 2,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Metrics Tab — Data Display", () => {
  test.beforeEach(async ({ page }) => {
    await setupJobDetailMocks(page, makeJob());

    // Mock telemetry endpoint
    await page.route("**/api/jobs/job-1/telemetry*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(TELEMETRY),
      });
    });

    // Mock job context endpoint (404 = no context available)
    await page.route("**/analytics/job-context/job-1*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    // Mock artifacts (empty for metrics)
    await page.route("**/api/jobs/job-1/artifacts*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [] }),
      });
    });

    // Mock sister session metrics
    await page.route("**/api/sister-sessions/metrics*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    // Mock model pricing
    await page.route("**/analytics/pricing*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
    });
  });

  test("shows stat cards with telemetry data", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Click the Metrics tab
    await page.getByRole("tab", { name: "Metrics" }).click();

    // Stat card labels should be visible
    await expect(page.getByText("Duration")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Tokens", { exact: true })).toBeVisible();
    await expect(page.getByText("Tools", { exact: true })).toBeVisible();
  });

  test("shows tool calls table after expanding", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    await page.getByRole("tab", { name: "Metrics" }).click();

    // Wait for metrics to load
    await expect(page.getByText("Duration")).toBeVisible({ timeout: 5_000 });

    // Expand the Tool Breakdown section
    await page.getByRole("button", { name: /Tool Breakdown/ }).click();

    // Tool names should appear in the tool calls section
    await expect(page.getByText("read_file").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("edit_file").first()).toBeVisible();
  });

  test("shows token breakdown stats", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    await page.getByRole("tab", { name: "Metrics" }).click();

    // Token breakdown should be visible
    await expect(page.getByText("Token Breakdown")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Input").first()).toBeVisible();
    await expect(page.getByText("Output").first()).toBeVisible();
  });
});

test.describe("Metrics Tab — Empty State", () => {
  test("shows no data message when telemetry unavailable", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob());

    // Mock telemetry endpoint with no data
    await page.route("**/api/jobs/job-1/telemetry*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ available: false }),
      });
    });

    await page.route("**/analytics/job-context/job-1*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });

    await page.route("**/api/jobs/job-1/artifacts*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [] }),
      });
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    await page.getByRole("tab", { name: "Metrics" }).click();

    await expect(page.getByText("No data available yet")).toBeVisible({ timeout: 5_000 });
  });
});
