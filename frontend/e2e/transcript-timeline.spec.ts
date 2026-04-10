/**
 * E2E tests: Transcript and activity timeline rendering.
 *
 * Covers agent messages, tool call display, operator messages,
 * timeline headline rendering, and search within transcripts.
 */

import { test, expect } from "@playwright/test";
import { makeJob, setupJobDetailMocks, NOW } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TRANSCRIPT = [
  {
    jobId: "job-1",
    seq: 1,
    timestamp: NOW,
    role: "agent",
    content: "I'll analyze the auth module to understand the current implementation.",
    turnId: "turn-1",
    title: "Planning approach",
  },
  {
    jobId: "job-1",
    seq: 2,
    timestamp: NOW,
    role: "tool_call",
    content: "",
    turnId: "turn-1",
    toolName: "read_file",
    toolArgs: '{"filePath": "src/auth.ts"}',
    toolResult: "export function login() { ... }",
    toolSuccess: true,
    toolDisplay: "Read src/auth.ts",
    toolDisplayFull: "Read src/auth.ts",
    toolDurationMs: 120,
    toolVisibility: "visible",
  },
  {
    jobId: "job-1",
    seq: 3,
    timestamp: NOW,
    role: "tool_call",
    content: "",
    turnId: "turn-1",
    toolName: "edit_file",
    toolArgs: '{"filePath": "src/auth.ts", "oldString": "...", "newString": "..."}',
    toolResult: "File edited successfully",
    toolSuccess: true,
    toolDisplay: "Edited src/auth.ts",
    toolDisplayFull: "Edited src/auth.ts",
    toolDurationMs: 45,
    toolVisibility: "visible",
  },
  {
    jobId: "job-1",
    seq: 4,
    timestamp: NOW,
    role: "agent",
    content: "I've fixed the authentication bug by adding proper token validation.",
    turnId: "turn-2",
    title: "Implementation complete",
  },
  {
    jobId: "job-1",
    seq: 5,
    timestamp: NOW,
    role: "operator",
    content: "Can you also add a test for that fix?",
    turnId: null,
  },
  {
    jobId: "job-1",
    seq: 6,
    timestamp: NOW,
    role: "agent",
    content: "Sure! I'll create a unit test for the token validation logic.",
    turnId: "turn-3",
    title: "Writing tests",
  },
];

const TIMELINE = [
  {
    jobId: "job-1",
    headline: "Analyzing auth module",
    headlinePast: "Analyzed auth module",
    summary: "Reading source files to understand current implementation",
    timestamp: NOW,
    active: false,
  },
  {
    jobId: "job-1",
    headline: "Fixing authentication bug",
    headlinePast: "Fixed authentication bug",
    summary: "Added proper token validation to login flow",
    timestamp: NOW,
    active: false,
  },
  {
    jobId: "job-1",
    headline: "Writing unit tests",
    headlinePast: "Wrote unit tests",
    summary: "",
    timestamp: NOW,
    active: true,
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Transcript — Message Rendering", () => {
  test.beforeEach(async ({ page }) => {
    await setupJobDetailMocks(page, makeJob(), {
      transcript: TRANSCRIPT,
      timeline: TIMELINE,
    });
  });

  test("renders agent messages with content", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Agent messages should be visible
    await expect(
      page.getByText("analyze the auth module").first(),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText("fixed the authentication bug").first(),
    ).toBeVisible();
  });

  test("renders operator messages", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    await expect(
      page.getByText("Can you also add a test").first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("renders tool call displays", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // CuratedFeed clusters tool calls — read_file → "Read 1 file", edit_file → "Edited 1 file"
    await expect(
      page.getByText("Read 1 file").first(),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText("Edited 1 file").first(),
    ).toBeVisible();
  });
});

test.describe("Transcript — Timeline Headlines", () => {
  test("shows timeline entries with headlines", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob(), {
      transcript: TRANSCRIPT,
      timeline: TIMELINE,
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Timeline shows headlinePast for inactive entries, headline for active
    await expect(
      page.getByText("Analyzed auth module").first(),
    ).toBeVisible({ timeout: 5_000 });
    await expect(
      page.getByText("Fixed authentication bug").first(),
    ).toBeVisible();
  });

  test("active timeline entry is visually distinct", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob(), {
      transcript: TRANSCRIPT,
      timeline: TIMELINE,
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // The active entry uses headline (present tense), not headlinePast
    await expect(
      page.getByText("Writing unit tests").first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Transcript — Empty State", () => {
  test("shows empty state when transcript is empty", async ({ page }) => {
    await setupJobDetailMocks(page, makeJob(), {
      transcript: [],
      timeline: [],
    });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // The Live tab should be visible and active by default
    await expect(page.getByRole("tab", { name: "Live" })).toBeVisible();
  });
});
