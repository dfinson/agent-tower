import { defineConfig } from "@playwright/test";
import process from "node:process";

export default defineConfig({
  testDir: "./tracker-e2e",
  testMatch: "tracker-sync.spec.ts",
  timeout: 150_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL:
      process.env.CODEPLANE_TRACKER_E2E_BASE_URL ??
      "http://127.0.0.1:18765",
    headless: true,
  },
  projects: [
    {
      name: "tracker-chromium",
      use: { browserName: "chromium" },
    },
  ],
});
