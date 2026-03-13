/**
 * End-to-end tests for Tower UI.
 *
 * These tests verify the full stack: backend + frontend running together.
 * The Playwright config starts the Tower server automatically.
 */

import { test, expect } from "@playwright/test";

test.describe("Health & Navigation", () => {
  test("loads the dashboard", async ({ page }) => {
    await page.goto("/");
    // Should see the Tower header
    await expect(page.locator(".app-header__title")).toContainText("Tower");
  });

  test("shows connection status", async ({ page }) => {
    await page.goto("/");
    // SSE should connect — status dot should be visible
    await expect(page.locator(".status-dot")).toBeVisible({ timeout: 10_000 });
  });

  test("navigates to create job screen", async ({ page }) => {
    await page.goto("/");
    await page.click("text=+ New Job");
    await expect(page).toHaveURL(/\/jobs\/new/);
    await expect(page.locator(".create-job__title")).toContainText("New Job");
  });

  test("navigates to settings screen", async ({ page }) => {
    await page.goto("/");
    // Click the Settings nav link
    const settingsLink = page.locator(".app-header__nav a", {
      hasText: "Settings",
    });
    await settingsLink.click();
    await expect(page).toHaveURL(/\/settings/);
  });
});

test.describe("Dashboard", () => {
  test("shows kanban columns on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    // Should see 4 kanban columns
    const columns = page.locator(".kanban-column__header");
    await expect(columns).toHaveCount(4);
    await expect(columns.nth(0)).toContainText("Active");
    await expect(columns.nth(1)).toContainText("Sign-off");
    await expect(columns.nth(2)).toContainText("Failed");
    await expect(columns.nth(3)).toContainText("History");
  });

  test("shows mobile filter tabs on small viewport", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");
    // Kanban should be hidden, mobile list visible
    const kanban = page.locator(".kanban");
    await expect(kanban).toBeHidden();
    const tabs = page.locator(".filter-tabs");
    await expect(tabs).toBeVisible();
  });
});

test.describe("Job Creation", () => {
  test("shows repo selector and prompt input", async ({ page }) => {
    await page.goto("/jobs/new");
    // Should have the prompt textarea
    const textarea = page.locator("textarea.form-textarea");
    await expect(textarea).toBeVisible();
  });

  test("has a create button", async ({ page }) => {
    await page.goto("/jobs/new");
    const createBtn = page.locator("button.btn--primary", {
      hasText: "Create Job",
    });
    await expect(createBtn).toBeVisible();
  });
});

test.describe("API Health", () => {
  test("health endpoint returns healthy", async ({ request }) => {
    const response = await request.get("/api/health");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe("healthy");
    expect(body.version).toBeDefined();
  });

  test("jobs endpoint returns list", async ({ request }) => {
    const response = await request.get("/api/jobs");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.items).toBeDefined();
    expect(Array.isArray(body.items)).toBe(true);
  });

  test("repos endpoint returns list", async ({ request }) => {
    const response = await request.get("/api/settings/repos");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.items).toBeDefined();
  });
});
