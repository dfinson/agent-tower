/**
 * Shared E2E test helpers and fixtures.
 *
 * DRY utilities used across multiple spec files to reduce duplication
 * of mock data, SSE builders, and route setup functions.
 */

import type { Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const NOW = new Date().toISOString();

// ---------------------------------------------------------------------------
// Job fixture builder
// ---------------------------------------------------------------------------

export function makeJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    title: "Test Job",
    prompt: "Fix the bug in auth module",
    state: "running",
    createdAt: NOW,
    updatedAt: NOW,
    completedAt: null,
    repo: "/tmp/test-repo",
    branch: "cpl/job-1",
    baseRef: "main",
    worktreePath: "/tmp/worktrees/job-1",
    prUrl: null,
    resolution: null,
    archivedAt: null,
    failureReason: null,
    progressHeadline: null,
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// SSE body builder
// ---------------------------------------------------------------------------

export function sseBody(events: { event: string; data: unknown }[]): string {
  return events
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)
    .join("");
}

// ---------------------------------------------------------------------------
// Common mock setup
// ---------------------------------------------------------------------------

/** Standard API mocks for SSE, jobs list, settings, SDKs, models. */
export async function setupBaseMocks(page: Page, jobs: unknown[] = []) {
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
        { event: "snapshot", data: { jobs, pendingApprovals: [] } },
      ]),
    });
  });

  await page.route("**/api/jobs?*", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: jobs, cursor: null, hasMore: false }),
    });
  });

  await page.route("**/api/settings", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        maxConcurrentJobs: 2,
        permissionMode: "full_auto",
        autoPush: false,
        cleanupWorktree: true,
        deleteBranchAfterMerge: false,
        artifactRetentionDays: 30,
        maxArtifactSizeMb: 100,
        autoArchiveDays: 14,
        verify: false,
        selfReview: false,
        maxTurns: 3,
        verifyPrompt: "",
        selfReviewPrompt: "",
      }),
    });
  });

  await page.route("**/api/settings/repos", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: ["/tmp/test-repo"] }),
    });
  });

  await page.route("**/api/sdks", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        default: "copilot",
        sdks: [{ id: "copilot", name: "GitHub Copilot", enabled: true, status: "ready" }],
      }),
    });
  });

  await page.route("**/api/models", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: "claude-sonnet-4-5-20250514", name: "Claude Sonnet 4.5" }]),
    });
  });
}

/** Full job detail mock setup — SSE + job + empty sub-resources. */
export async function setupJobDetailMocks(
  page: Page,
  job: ReturnType<typeof makeJob>,
  overrides: {
    transcript?: unknown[];
    timeline?: unknown[];
    diff?: unknown[];
    approvals?: unknown[];
    snapshot?: unknown;
    artifacts?: unknown[];
  } = {},
) {
  await setupBaseMocks(page, [job]);

  const jobId = job.id as string;

  await page.route(`**/api/jobs/${jobId}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(job),
    });
  });

  await page.route(`**/api/jobs/${jobId}/transcript*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overrides.transcript ?? []),
    });
  });

  await page.route(`**/api/jobs/${jobId}/timeline*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overrides.timeline ?? []),
    });
  });

  await page.route(`**/api/jobs/${jobId}/diff*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overrides.diff ?? []),
    });
  });

  await page.route(`**/api/jobs/${jobId}/approvals*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overrides.approvals ?? []),
    });
  });

  if (overrides.snapshot) {
    await page.route(`**/api/jobs/${jobId}/snapshot*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(overrides.snapshot),
      });
    });
  }

  if (overrides.artifacts) {
    await page.route(`**/api/jobs/${jobId}/artifacts*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(overrides.artifacts),
      });
    });
  }
}
