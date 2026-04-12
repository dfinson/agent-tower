/**
 * E2E tests: Shared Job View (/shared/:token).
 *
 * Covers snapshot loading, error states, read-only rendering,
 * tab switching, and SSE event handling for shared links.
 */

import { test, expect } from "@playwright/test";
import { makeJob, sseBody, NOW } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SHARE_TOKEN = "abc-share-token-123";

const SHARED_SNAPSHOT = {
  job: {
    ...makeJob({ title: "Shared Test Job", state: "completed", completedAt: NOW }),
  },
  logs: [],
  transcript: [
    {
      jobId: "job-1",
      seq: 1,
      timestamp: NOW,
      role: "agent",
      content: "I fixed the authentication issue by adding token validation.",
      turnId: "turn-1",
      title: "Fix applied",
    },
  ],
  diff: [
    {
      path: "src/auth.ts",
      status: "modified",
      additions: 5,
      deletions: 2,
      hunks: [
        {
          header: "@@ -10,5 +10,8 @@",
          lines: [
            { type: "context", content: "function login() {", oldLine: 10, newLine: 10 },
            { type: "deletion", content: "  return false;", oldLine: 11, newLine: null },
            { type: "addition", content: "  const token = generateToken();", oldLine: null, newLine: 11 },
            { type: "addition", content: "  return validateToken(token);", oldLine: null, newLine: 12 },
            { type: "context", content: "}", oldLine: 12, newLine: 13 },
          ],
        },
      ],
    },
  ],
  approvals: [],
  timeline: [],
  turnSummaries: [
    {
      turnId: "turn-1",
      title: "Fix applied",
      activityId: "act-1",
      activityLabel: "Fixing auth",
      activityStatus: "done",
      isNewActivity: true,
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function setupSharedMocks(page: import("@playwright/test").Page, snapshot = SHARED_SNAPSHOT) {
  // Shared snapshot endpoint
  await page.route(`**/api/share/${SHARE_TOKEN}/snapshot`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(snapshot),
    });
  });

  // Shared SSE endpoint
  await page.route(`**/api/share/${SHARE_TOKEN}/events*`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
      body: sseBody([{ event: "session_heartbeat", data: {} }]),
    });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Shared Job View — Loading & Rendering", () => {
  test("renders shared job with title and state", async ({ page }) => {
    await setupSharedMocks(page);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Completed").first()).toBeVisible();
  });

  test("shows breadcrumb navigation", async ({ page }) => {
    await setupSharedMocks(page);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Shared View")).toBeVisible();
  });

  test("displays job metadata", async ({ page }) => {
    await setupSharedMocks(page);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Branch")).toBeVisible();
    await expect(page.getByText("cpl/job-1")).toBeVisible();
    await expect(page.getByText("Base")).toBeVisible();
    await expect(page.getByText("main")).toBeVisible();
  });

  test("renders transcript content on Live tab", async ({ page }) => {
    await setupSharedMocks(page);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("fixed the authentication issue")).toBeVisible({ timeout: 5_000 });
  });

  test("shows failure reason for failed jobs", async ({ page }) => {
    const failedSnapshot = {
      ...SHARED_SNAPSHOT,
      job: {
        ...SHARED_SNAPSHOT.job,
        state: "failed",
        failureReason: "Out of memory during compilation",
        completedAt: null,
      },
    };
    await setupSharedMocks(page, failedSnapshot);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Out of memory during compilation")).toBeVisible();
  });
});

test.describe("Shared Job View — Tab Switching", () => {
  test("switches to Changes tab and shows diff", async ({ page }) => {
    await setupSharedMocks(page);
    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Shared Test Job")).toBeVisible({ timeout: 5_000 });

    // Click Changes tab
    await page.getByRole("tab", { name: "Changes" }).click();

    // Should show the diff file
    await expect(page.getByText("src/auth.ts").first()).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Shared Job View — Error States", () => {
  test("shows error for expired share link (404)", async ({ page }) => {
    await page.route(`**/api/share/${SHARE_TOKEN}/snapshot`, async (route) => {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Not found" }) });
    });

    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Share link unavailable")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Share link expired or invalid")).toBeVisible();
  });

  test("shows error for server failure (500)", async ({ page }) => {
    await page.route(`**/api/share/${SHARE_TOKEN}/snapshot`, async (route) => {
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal error" }) });
    });
    // Suppress retry-related console errors
    await page.route(`**/api/share/${SHARE_TOKEN}/events*`, async (route) => {
      await route.abort();
    });

    await page.goto(`/shared/${SHARE_TOKEN}`);

    await expect(page.getByText("Share link unavailable")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Failed to load shared job")).toBeVisible();
  });
});
