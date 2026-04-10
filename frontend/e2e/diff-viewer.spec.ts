/**
 * E2E tests: Diff viewer tab.
 *
 * Covers rendering file list, syntax-highlighted diffs with additions/deletions,
 * file status badges, and empty diff state.
 */

import { test, expect } from "@playwright/test";
import { makeJob, setupJobDetailMocks, NOW } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const DIFF_FILES = [
  {
    path: "src/auth.ts",
    status: "modified",
    additions: 12,
    deletions: 3,
    hunks: [
      {
        oldStart: 1,
        oldLines: 8,
        newStart: 1,
        newLines: 17,
        lines: [
          { type: "context", content: "import { verify } from 'jsonwebtoken';" },
          { type: "context", content: "" },
          { type: "deletion", content: "export function login(token: string) {" },
          { type: "addition", content: "export function login(token: string): boolean {" },
          { type: "addition", content: "  if (!token || token.length === 0) {" },
          { type: "addition", content: "    throw new Error('Token is required');" },
          { type: "addition", content: "  }" },
          { type: "context", content: "  const decoded = verify(token, SECRET);" },
          { type: "context", content: "  return !!decoded;" },
          { type: "context", content: "}" },
        ],
      },
    ],
  },
  {
    path: "src/auth.test.ts",
    status: "added",
    additions: 25,
    deletions: 0,
    hunks: [
      {
        oldStart: 0,
        oldLines: 0,
        newStart: 1,
        newLines: 5,
        lines: [
          { type: "addition", content: 'import { login } from "./auth";' },
          { type: "addition", content: "" },
          { type: "addition", content: 'describe("login", () => {' },
          { type: "addition", content: "  it('throws for empty token', () => {" },
          { type: "addition", content: "    expect(() => login('')).toThrow();" },
        ],
      },
    ],
  },
  {
    path: "src/legacy.ts",
    status: "deleted",
    additions: 0,
    deletions: 15,
    hunks: [
      {
        oldStart: 1,
        oldLines: 3,
        newStart: 0,
        newLines: 0,
        lines: [
          { type: "deletion", content: "// Legacy auth module" },
          { type: "deletion", content: "export function oldLogin() {}" },
          { type: "deletion", content: "export function oldLogout() {}" },
        ],
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Diff Viewer — File List", () => {
  test.beforeEach(async ({ page }) => {
    const job = makeJob({ state: "review", resolution: "unresolved", completedAt: NOW });
    await setupJobDetailMocks(page, job, { diff: DIFF_FILES });
  });

  test("Changes tab shows file count", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // Click the Changes tab
    const changesTab = page.getByRole("tab", { name: /Changes/i });
    await expect(changesTab).toBeVisible();
    await changesTab.click();

    // Should show diff file paths
    await expect(page.getByText("src/auth.ts").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("src/auth.test.ts").first()).toBeVisible();
    await expect(page.getByText("src/legacy.ts").first()).toBeVisible();
  });

  test("shows addition and deletion counts", async ({ page }) => {
    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    const changesTab = page.getByRole("tab", { name: /Changes/i });
    await changesTab.click();

    // Addition/deletion counts should be visible somewhere in the diff view
    // (typically as +12 -3 badge on each file)
    await expect(page.getByText("+12").first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("-3").first()).toBeVisible();
  });
});

test.describe("Diff Viewer — Diff Content", () => {
  test("shows diff content with additions and deletions", async ({ page }) => {
    const job = makeJob({ state: "review", resolution: "unresolved", completedAt: NOW });
    await setupJobDetailMocks(page, job, { diff: DIFF_FILES });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    const changesTab = page.getByRole("tab", { name: /Changes/i });
    await changesTab.click();

    // Click on the first file to view its diff
    await page.getByText("src/auth.ts").first().click();

    // Should show diff content — look for code from the hunks
    await expect(
      page.getByText("Token is required").first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Diff Viewer — Empty State", () => {
  test("shows message when no changes exist", async ({ page }) => {
    const job = makeJob({ state: "running" });
    await setupJobDetailMocks(page, job, { diff: [] });

    await page.goto("/jobs/job-1");
    await expect(page.getByText("job-1", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    const changesTab = page.getByRole("tab", { name: /Changes/i });
    await changesTab.click();

    // Should show empty state or "no changes" message
    await expect(
      page.getByText(/no (changes|files|diffs)/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});
