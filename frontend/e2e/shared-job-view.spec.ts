/**
 * E2E test: Shared Job View route remains disabled.
 *
 * The app currently keeps /shared/:token commented out, so this spec asserts
 * that navigating there does not render a shared-view shell.
 */

import { test, expect } from "@playwright/test";

const SHARE_TOKEN = "abc-share-token-123";

test("shared job view route stays disabled", async ({ page }) => {
  await page.goto(`/shared/${SHARE_TOKEN}`);

  await expect(page.locator("main")).toBeEmpty();
  await expect(page.getByText("Shared Test Job")).toHaveCount(0);
  await expect(page.getByText("Share link unavailable")).toHaveCount(0);
});
