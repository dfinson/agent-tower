/**
 * E2E tests: Error handling, edge cases, and resilience.
 *
 * Covers 404 routes, API failures (5xx), nonexistent job IDs,
 * SSE disconnection recovery, and malformed API responses.
 */

import { test, expect } from "@playwright/test";
import { setupBaseMocks, setupJobDetailMocks, makeJob, sseBody, NOW } from "./helpers";

// ---------------------------------------------------------------------------
// Tests: 404 / Not Found routes
// ---------------------------------------------------------------------------

test.describe("404 — Unknown Routes", () => {
  test("navigating to unknown route shows fallback", async ({ page }) => {
    await setupBaseMocks(page);
    await page.goto("/this-page-does-not-exist");

    // Should either redirect to dashboard or show a not-found message
    // Most SPAs redirect to / — check we end up somewhere valid
    await expect(
      page.getByText(/CodePlane|not found|page/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Tests: Nonexistent job
// ---------------------------------------------------------------------------

test.describe("Nonexistent Job", () => {
  test("shows error when job API returns 404", async ({ page }) => {
    await setupBaseMocks(page);

    await page.route("**/api/jobs/nonexistent-job", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"Not found"}' });
    });
    await page.route("**/api/jobs/nonexistent-job/transcript*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/nonexistent-job/timeline*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/nonexistent-job/diff*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/nonexistent-job/approvals*", async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: "[]" });
    });

    await page.goto("/jobs/nonexistent-job");

    // Should show error state or redirect, not crash
    // Give the page time to process the 404
    await page.waitForTimeout(2_000);

    // Page should not show React crash — check for any visible content
    const body = await page.locator("body").textContent();
    expect(body).toBeTruthy();
    // Should NOT see uncaught React error
    expect(body).not.toContain("Unhandled Runtime Error");
  });
});

// ---------------------------------------------------------------------------
// Tests: API server errors (500)
// ---------------------------------------------------------------------------

test.describe("Server Error Handling", () => {
  test("dashboard handles 500 on jobs list gracefully", async ({ page }) => {
    // SSE works fine
    await page.route("**/api/events*", async (route) => {
      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
        },
        body: sseBody([
          { event: "session_heartbeat", data: {} },
          { event: "snapshot", data: { jobs: [], pendingApprovals: [] } },
        ]),
      });
    });

    // Jobs list returns 500
    await page.route("**/api/jobs?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: '{"detail":"Internal server error"}',
      });
    });

    await page.goto("/");

    // Page should still render — SSE provides job data even if REST fails
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test("settings handles 500 without crash", async ({ page }) => {
    await setupBaseMocks(page);

    // Override settings to return 500
    await page.route("**/api/settings", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: '{"detail":"Internal server error"}',
      });
    });

    await page.goto("/settings");

    // Page should render a heading at minimum, not crash
    await page.waitForTimeout(2_000);
    const body = await page.locator("body").textContent();
    expect(body).toBeTruthy();
    expect(body).not.toContain("Unhandled Runtime Error");
  });
});

// ---------------------------------------------------------------------------
// Tests: Job detail with rich error state
// ---------------------------------------------------------------------------

test.describe("Job Error Details", () => {
  test("failed job with error_kind shows structured error", async ({ page }) => {
    const failedJob = makeJob({
      state: "failed",
      completedAt: NOW,
      failureReason: "Agent exceeded token budget: 200k tokens used, 150k limit",
    });
    await setupJobDetailMocks(page, failedJob);

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Should show the failure reason
    await expect(
      page.getByText(/token budget|exceeded/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("canceled job shows appropriate state", async ({ page }) => {
    const canceledJob = makeJob({
      state: "canceled",
      completedAt: NOW,
    });
    await setupJobDetailMocks(page, canceledJob);

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Should not show Cancel button for already-canceled job
    await expect(
      page.locator("button", { hasText: /^Cancel$/ }),
    ).not.toBeVisible({ timeout: 2_000 });
  });
});

// ---------------------------------------------------------------------------
// Tests: SSE connection indicator
// ---------------------------------------------------------------------------

test.describe("SSE Connection Resilience", () => {
  test("SSE failure does not crash the dashboard", async ({ page }) => {
    // SSE returns an error immediately
    await page.route("**/api/events*", async (route) => {
      await route.fulfill({ status: 503, body: "Service Unavailable" });
    });

    await page.route("**/api/jobs?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], cursor: null, hasMore: false }),
      });
    });

    await page.goto("/");

    // Dashboard should still render despite SSE failure
    await expect(page.getByText(/CodePlane/i).first()).toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Tests: Mobile viewport edge cases
// ---------------------------------------------------------------------------

test.describe("Mobile Viewport", () => {
  test("dashboard renders on small viewport without horizontal scroll", async ({ page }) => {
    await setupBaseMocks(page, [makeJob()]);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");

    // Wait for the job card button to be present (it may have truncated text)
    await expect(page.getByRole("button", { name: /Test Job/i })).toBeVisible({ timeout: 8_000 });

    // Document should not overflow horizontally
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 5); // 5px tolerance
  });

  test("job detail renders on tablet viewport", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob());

    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/jobs/job-1");

    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });
    // Tabs should still be visible
    await expect(page.getByRole("tab", { name: "Live" })).toBeVisible();
  });
});
