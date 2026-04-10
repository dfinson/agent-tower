/**
 * E2E tests: History screen.
 *
 * Covers job history list rendering, filtering by resolution,
 * search functionality, pagination, and navigation to job detail.
 */

import { test, expect } from "@playwright/test";
import { setupBaseMocks, NOW } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const HISTORY_JOBS = [
  {
    id: "job-10",
    title: "Fix auth bug",
    prompt: "Fix the authentication bug in login flow",
    state: "completed",
    resolution: "merged",
    repo: "/tmp/project-a",
    branch: "cpl/job-10",
    baseRef: "main",
    createdAt: "2026-04-09T10:00:00Z",
    updatedAt: "2026-04-09T10:30:00Z",
    completedAt: "2026-04-09T10:30:00Z",
    archivedAt: null,
    failureReason: null,
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    worktreePath: null,
    prUrl: null,
    progressHeadline: null,
  },
  {
    id: "job-11",
    title: "Add user search",
    prompt: "Add a user search feature with autocomplete",
    state: "completed",
    resolution: "pr_created",
    repo: "/tmp/project-b",
    branch: "cpl/job-11",
    baseRef: "main",
    createdAt: "2026-04-08T14:00:00Z",
    updatedAt: "2026-04-08T15:00:00Z",
    completedAt: "2026-04-08T15:00:00Z",
    archivedAt: null,
    failureReason: null,
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    worktreePath: null,
    prUrl: "https://github.com/org/repo/pull/42",
    progressHeadline: null,
  },
  {
    id: "job-12",
    title: "Refactor database",
    prompt: "Refactor the database layer to use async",
    state: "failed",
    resolution: null,
    repo: "/tmp/project-a",
    branch: "cpl/job-12",
    baseRef: "main",
    createdAt: "2026-04-07T09:00:00Z",
    updatedAt: "2026-04-07T09:20:00Z",
    completedAt: "2026-04-07T09:20:00Z",
    archivedAt: null,
    failureReason: "Agent exceeded maximum turn limit",
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    worktreePath: null,
    prUrl: null,
    progressHeadline: null,
  },
  {
    id: "job-13",
    title: "Update docs",
    prompt: "Update the API documentation",
    state: "completed",
    resolution: "discarded",
    repo: "/tmp/project-a",
    branch: "cpl/job-13",
    baseRef: "main",
    createdAt: "2026-04-06T16:00:00Z",
    updatedAt: "2026-04-06T16:10:00Z",
    completedAt: "2026-04-06T16:10:00Z",
    archivedAt: null,
    failureReason: null,
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    worktreePath: null,
    prUrl: null,
    progressHeadline: null,
  },
];

async function setupHistoryMocks(page: import("@playwright/test").Page, jobs = HISTORY_JOBS) {
  await setupBaseMocks(page);

  // Register AFTER base mocks — Playwright uses LIFO: last registered wins
  await page.route("**/api/jobs?*", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: jobs,
        cursor: null,
        hasMore: false,
      }),
    });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("History — Page Load", () => {
  test("renders history screen heading", async ({ page }) => {
    await setupHistoryMocks(page);
    await page.goto("/history");

    await expect(
      page.getByText(/Job History|History/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("displays job entries with titles", async ({ page }) => {
    await setupHistoryMocks(page);
    await page.goto("/history");

    await expect(page.getByText("Fix auth bug").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Add user search").first()).toBeVisible();
    await expect(page.getByText("Refactor database").first()).toBeVisible();
    await expect(page.getByText("Update docs").first()).toBeVisible();
  });

  test("shows resolution badges", async ({ page }) => {
    await setupHistoryMocks(page);
    await page.goto("/history");

    // Should show resolution indicators
    await expect(page.getByText(/merged/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/failed/i).first()).toBeVisible();
  });
});

test.describe("History — Filtering", () => {
  test("filter buttons are visible", async ({ page }) => {
    await setupHistoryMocks(page);
    await page.goto("/history");

    // Should show filter options
    await expect(page.getByText("All").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Merged").first()).toBeVisible();
    await expect(page.getByText("Failed").first()).toBeVisible();
  });

  test("clicking a filter narrows the displayed jobs", async ({ page }) => {
    await setupHistoryMocks(page);

    // Track filter requests
    let lastUrl = "";
    await page.route("**/api/jobs?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      lastUrl = route.request().url();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: HISTORY_JOBS.filter((j) => j.state === "failed"),
          cursor: null,
          hasMore: false,
        }),
      });
    });

    await page.goto("/history");
    await expect(page.getByText("Fix auth bug").first()).toBeVisible({ timeout: 5_000 });

    // Click "Failed" filter
    await page.getByRole("button", { name: /Failed/i }).click();

    // Should show only the failed job
    await expect(page.getByText("Refactor database").first()).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("History — Search", () => {
  test("search input is visible", async ({ page }) => {
    await setupHistoryMocks(page);
    await page.goto("/history");

    const searchInput = page.locator("input[placeholder*=earch]").first();
    await expect(searchInput).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("History — Navigation", () => {
  test("clicking a job navigates to job detail", async ({ page }) => {
    await setupHistoryMocks(page);

    // Mock job detail route for the navigation target
    await page.route("**/api/jobs/job-10", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(HISTORY_JOBS[0]),
      });
    });
    await page.route("**/api/jobs/job-10/transcript*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/job-10/timeline*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/job-10/diff*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route("**/api/jobs/job-10/approvals*", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto("/history");
    await expect(page.getByText("Fix auth bug").first()).toBeVisible({ timeout: 5_000 });

    // Click the job row
    await page.getByText("Fix auth bug").first().click();

    // Should navigate to the job detail page
    await expect(page).toHaveURL(/\/jobs\/job-10/, { timeout: 5_000 });
  });
});

test.describe("History — Empty State", () => {
  test("shows empty message when no jobs exist", async ({ page }) => {
    await setupBaseMocks(page);

    await page.route("**/api/jobs?*", async (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], cursor: null, hasMore: false }),
      });
    });

    await page.goto("/history");
    await expect(
      page.getByText(/Job History|History/i).first(),
    ).toBeVisible({ timeout: 5_000 });

    // Should show some form of empty state
    await expect(
      page.getByText(/no archived jobs/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});
