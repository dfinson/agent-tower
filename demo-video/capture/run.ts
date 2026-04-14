/**
 * Playwright capture script — screenshots of the real CodePlane frontend
 * with mock API data injected via route interception.
 *
 * Usage:
 *   1. Start the Vite dev server:  cd frontend && npx vite --port 5173
 *   2. Run captures:               cd demo-video && npx tsx capture/run.ts
 *   3. Screenshots land in:        demo-video/public/captures/
 */

import { chromium, type Page, type BrowserContext, type Browser } from "playwright";
import * as path from "path";
import * as fs from "fs";
import {
  mockJobs,
  mockHealth,
  mockSdks,
  mockModels,
  mockSettings,
  mockRepoList,
  mockScorecard,
  mockModelComparison,
  mockAnalyticsTools,
  mockAnalyticsRepos,
  mockCostDrivers,
  mockObservations,
  mockOverview,
  runningJobTranscript,
  runningJobTimeline,
  runningJobPlan,
  runningJobTurnSummaries,
  approvalJobApprovals,
  reviewJobDiff,
} from "./fixtures";

const BASE = process.env.CAPTURE_BASE_URL ?? "http://localhost:8080";
const OUT = path.resolve(__dirname, "..", "public", "captures");

// ---------------------------------------------------------------------------
// Route interception: mock every API endpoint the frontend calls
// ---------------------------------------------------------------------------

async function setupRoutes(page: Page | BrowserContext) {
  // Health
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: mockHealth }),
  );

  // SDKs
  await page.route("**/api/sdks", (route) =>
    route.fulfill({ json: mockSdks }),
  );

  // Models
  await page.route("**/api/models**", (route) =>
    route.fulfill({ json: mockModels }),
  );

  // Settings
  await page.route("**/api/settings", (route) => {
    if (route.request().url().includes("/repos")) return route.continue();
    return route.fulfill({ json: mockSettings });
  });
  await page.route("**/api/settings/repos", (route) =>
    route.fulfill({ json: mockRepoList }),
  );
  await page.route("**/api/settings/repos/*", (route) =>
    route.fulfill({
      json: {
        path: route.request().url().split("/repos/")[1],
        originUrl: "https://github.com/acme/repo.git",
        baseBranch: "main",
        currentBranch: "main",
        activeJobCount: 1,
        platform: "github",
      },
    }),
  );

  // Jobs list
  await page.route("**/api/jobs?**", (route) =>
    route.fulfill({
      json: { items: mockJobs, cursor: null, hasMore: false },
    }),
  );
  await page.route(/\/api\/jobs$/, (route) =>
    route.fulfill({
      json: { items: mockJobs, cursor: null, hasMore: false },
    }),
  );

  // Job detail — match specific job IDs
  await page.route(/\/api\/jobs\/[\w-]+\/snapshot/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)\//)?.[1];
    const job = mockJobs.find((j) => j.id === jobId) ?? mockJobs[0];
    return route.fulfill({
      json: {
        job,
        logs: [],
        transcript: jobId === "customer-email-search" ? runningJobTranscript : [],
        diff: jobId === "ticket-list-pagination" ? reviewJobDiff : [],
        approvals: jobId === "keyboard-shortcut-hints" ? approvalJobApprovals : [],
        timeline: jobId === "customer-email-search" ? runningJobTimeline : [],
        steps: jobId === "customer-email-search" ? runningJobPlan : [],
        turnSummaries: jobId === "customer-email-search" ? runningJobTurnSummaries : [],
      },
    });
  });

  await page.route(/\/api\/jobs\/[\w-]+\/transcript/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)\//)?.[1];
    return route.fulfill({
      json: jobId === "customer-email-search" ? runningJobTranscript : [],
    });
  });

  await page.route(/\/api\/jobs\/[\w-]+\/timeline/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)\//)?.[1];
    return route.fulfill({
      json: jobId === "customer-email-search" ? runningJobTimeline : [],
    });
  });

  await page.route(/\/api\/jobs\/[\w-]+\/diff/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)\//)?.[1];
    return route.fulfill({
      json: jobId === "ticket-list-pagination" ? reviewJobDiff : [],
    });
  });

  await page.route(/\/api\/jobs\/[\w-]+\/approvals/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)\//)?.[1];
    return route.fulfill({
      json: jobId === "keyboard-shortcut-hints" ? approvalJobApprovals : [],
    });
  });

  await page.route(/\/api\/jobs\/[\w-]+\/artifacts/, (route) =>
    route.fulfill({ json: { items: [] } }),
  );

  await page.route(/\/api\/jobs\/[\w-]+\/telemetry/, (route) =>
    route.fulfill({
      json: {
        turns: [],
        tokensByRole: {},
        costByCategory: {},
        totalCostUsd: 0.42,
        totalTokens: 28400,
        cacheStats: { hits: 0, misses: 0 },
      },
    }),
  );

  // Single job fetch
  await page.route(/\/api\/jobs\/[\w-]+$/, (route) => {
    const jobId = route.request().url().match(/\/jobs\/([\w-]+)$/)?.[1];
    const job = mockJobs.find((j) => j.id === jobId);
    if (job) return route.fulfill({ json: job });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });

  // Analytics
  await page.route("**/api/analytics/scorecard**", (route) =>
    route.fulfill({ json: mockScorecard }),
  );
  await page.route("**/api/analytics/model-comparison**", (route) =>
    route.fulfill({ json: mockModelComparison }),
  );
  await page.route("**/api/analytics/tools**", (route) =>
    route.fulfill({ json: mockAnalyticsTools }),
  );
  await page.route("**/api/analytics/repos**", (route) =>
    route.fulfill({ json: mockAnalyticsRepos }),
  );
  await page.route("**/api/analytics/cost-drivers**", (route) =>
    route.fulfill({ json: mockCostDrivers }),
  );
  await page.route("**/api/analytics/observations**", (route) =>
    route.fulfill({ json: mockObservations }),
  );
  await page.route("**/api/analytics/overview**", (route) =>
    route.fulfill({ json: mockOverview }),
  );
  await page.route("**/api/analytics/jobs**", (route) =>
    route.fulfill({ json: { period: 7, jobs: [], total: 0 } }),
  );
  await page.route("**/api/analytics/pricing**", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.route("**/api/analytics/fleet-cost-drivers**", (route) =>
    route.fulfill({ json: mockCostDrivers }),
  );

  // Approval resolution — /api/approvals/{id}/resolve
  await page.route(/\/api\/approvals\/[\w-]+\/resolve/, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 200, json: { status: "approved" } });
    }
    return route.fulfill({ status: 200, json: {} });
  });

  // SSE — never respond so EventSource stays connecting (no error loop)
  await page.route("**/api/events**", (route) => {
    // Intentionally never fulfilled — the request hangs.
    // We patch the connection status in the DOM after load.
  });
}

// ---------------------------------------------------------------------------
// DOM fixup: patch the connection status badge to show "Connected"
// ---------------------------------------------------------------------------

async function patchConnectionBadge(page: Page) {
  await page.evaluate(() => {
    const badge = document.querySelector(
      '[aria-label*="Connection status"]',
    ) as HTMLElement | null;
    if (!badge) return;
    badge.setAttribute("aria-label", "Connection status: Connected");
    // Find the dot (first child span or first element)
    const dot = badge.querySelector("span:first-child") as HTMLElement | null;
    if (dot) {
      dot.style.backgroundColor = "hsl(142 71% 45%)"; // green-500
      dot.style.boxShadow = "0 0 0 2px hsl(142 71% 45% / 0.2)";
    }
    // Update text
    const walker = document.createTreeWalker(
      badge,
      NodeFilter.SHOW_TEXT,
      null,
    );
    let text: Text | null;
    while ((text = walker.nextNode() as Text | null)) {
      if (text.textContent?.trim()) {
        text.textContent = "Connected";
        break;
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Capture functions
// ---------------------------------------------------------------------------

async function captureDashboard(page: Page) {
  console.log("  → Dashboard (desktop)");
  await page.goto(BASE);
  // Wait for kanban columns to appear
  await page.waitForSelector('[role="region"]', { timeout: 10_000 });
  await page.waitForTimeout(800); // let all cards settle
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "dashboard-desktop.png"),
    type: "png",
  });
}

async function captureJobRunning(page: Page) {
  console.log("  → Job detail — running (live tab)");
  await page.goto(`${BASE}/jobs/customer-email-search`);
  // Wait for the job title or job detail to render
  await page.waitForSelector("text=Add customer email search", {
    timeout: 10_000,
  });
  await page.waitForTimeout(1200); // let transcript render
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "job-running-live.png"),
    type: "png",
  });
}

async function captureJobDiff(page: Page) {
  console.log("  → Job detail — diff (changes tab)");
  await page.goto(`${BASE}/jobs/ticket-list-pagination`);
  await page.waitForSelector("text=Add pagination", { timeout: 10_000 });
  await page.waitForTimeout(800);
  // Click the Changes tab
  const changesTab = page.getByRole("tab", { name: /changes/i });
  if (await changesTab.isVisible()) {
    await changesTab.click();
    await page.waitForTimeout(1500); // Monaco needs time to mount
  }
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "job-diff.png"),
    type: "png",
  });
}

async function captureJobApproval(page: Page) {
  console.log("  → Job detail — approval banner");
  await page.goto(`${BASE}/jobs/keyboard-shortcut-hints`);
  await page.waitForSelector("text=Add keyboard shortcut hints", {
    timeout: 10_000,
  });
  await page.waitForTimeout(1000);
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "job-approval.png"),
    type: "png",
  });
}

async function captureAnalytics(page: Page) {
  console.log("  → Analytics (top section)");
  await page.goto(`${BASE}/analytics`);
  // Wait for the spinner to disappear and content to render
  await page.waitForSelector("text=Budget", { timeout: 15_000 });
  await page.waitForTimeout(1200);
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "analytics-top.png"),
    type: "png",
  });

  // Scroll to model comparison
  console.log("  → Analytics (model comparison)");
  await page.evaluate(() => {
    // Find the model comparison heading and scroll to it
    const heading = Array.from(document.querySelectorAll("h3, h2")).find(
      (el) =>
        el.textContent?.toLowerCase().includes("model") &&
        el.textContent?.toLowerCase().includes("comparison"),
    );
    heading?.scrollIntoView({ behavior: "instant", block: "start" });
  });
  await page.waitForTimeout(500);
  await page.screenshot({
    path: path.join(OUT, "analytics-models.png"),
    type: "png",
  });
}

async function captureJobMetrics(page: Page) {
  console.log("  → Job detail — metrics tab");
  await page.goto(`${BASE}/jobs/customer-email-search`);
  await page.waitForSelector("text=Add customer email search", {
    timeout: 10_000,
  });
  await page.waitForTimeout(800);
  // Click the Metrics tab
  const metricsTab = page.getByRole("tab", { name: /metrics/i });
  if (await metricsTab.isVisible()) {
    await metricsTab.click();
    await page.waitForTimeout(1200);
  }
  await patchConnectionBadge(page);
  await page.screenshot({
    path: path.join(OUT, "job-metrics.png"),
    type: "png",
  });
}

// ---------------------------------------------------------------------------
// Video captures — record real interactions as WebM clips
// ---------------------------------------------------------------------------

const VIDEO_DIR = path.resolve(OUT, "videos");

async function setupVideoContext(browser: Browser) {
  fs.mkdirSync(VIDEO_DIR, { recursive: true });
  const ctx = await browser.newContext({
    viewport: { width: 768, height: 432 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    recordVideo: {
      dir: VIDEO_DIR,
      size: { width: 1536, height: 864 },
    },
  });

  // Set up init scripts and routes on the CONTEXT (before page creation)
  // so the video recording starts clean when the page is created.
  await ctx.addInitScript(() => {
    (window as any).EventSource = class FakeEventSource extends EventTarget {
      readyState = 0;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      constructor(url: string | URL, _init?: EventSourceInit) {
        super();
        this.url = String(url);
        queueMicrotask(() => {
          this.readyState = 1;
          const openEvt = new Event("open");
          this.onopen?.(openEvt as any);
          this.dispatchEvent(openEvt);
          const snapshotData = JSON.stringify({
            jobs: (window as any).__mockJobs ?? [],
            pendingApprovals: (window as any).__mockApprovals ?? [],
          });
          const snapshotEvt = new MessageEvent("snapshot", { data: snapshotData });
          this.dispatchEvent(snapshotEvt);
          const hb = new MessageEvent("session_heartbeat", { data: "{}" });
          this.dispatchEvent(hb);
        });
      }
      close() { this.readyState = 2; }
    } as any;
  });
  await ctx.addInitScript(
    (data: { jobs: unknown[]; approvals: unknown[] }) => {
      (window as any).__mockJobs = data.jobs;
      (window as any).__mockApprovals = data.approvals;
    },
    { jobs: mockJobs, approvals: approvalJobApprovals },
  );

  // Register routes on the context (page-level routes override these,
  // but for video we only use context-level)
  await setupRoutes(ctx);

  return ctx;
}

async function captureVideoJobCreation(browser: Browser) {
  console.log("  → Video: Job creation flow");
  const ctx = await setupVideoContext(browser);
  // Page creation starts the recording — navigate immediately
  const page = await ctx.newPage();
  await page.goto(`${BASE}/jobs/new`);
  await page.waitForSelector("textarea", { timeout: 10_000 });
  await page.waitForTimeout(500);
  await patchConnectionBadge(page);
  await page.waitForTimeout(300);

  const promptArea = page.locator("textarea").first();
  await promptArea.click();
  await page.waitForTimeout(150);
  await promptArea.type(
    "Add customer email search to the ticket list endpoint and add tests",
    { delay: 30 },
  );
  await page.waitForTimeout(800);

  const createBtn = page.locator('button:has-text("Create Job")');
  await createBtn.click();
  await page.waitForTimeout(1200);

  await page.close();
  await page.video()!.saveAs(path.join(OUT, "video-job-creation.webm"));
  await ctx.close();
  console.log("    ✓ video-job-creation.webm");
}

async function captureVideoApprovalClick(browser: Browser) {
  console.log("  → Video: Approval click");
  const ctx = await setupVideoContext(browser);
  const page = await ctx.newPage();
  await page.goto(`${BASE}/jobs/keyboard-shortcut-hints`);
  await page.waitForSelector("text=Add keyboard shortcut hints", {
    timeout: 10_000,
  });
  await page.waitForTimeout(800);
  await patchConnectionBadge(page);
  await page.waitForTimeout(400);

  const approveBtn = page.locator('button:has-text("Approve")').first();
  if (await approveBtn.isVisible()) {
    const box = await approveBtn.boundingBox();
    if (box) {
      const vw = page.viewportSize()!;
      await page.mouse.move(vw.width * 0.75, vw.height * 0.35);
      await page.waitForTimeout(250);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {
        steps: 15,
      });
      await page.waitForTimeout(300);
    }
    await approveBtn.click();
    await page.waitForTimeout(1200);
  }

  await page.close();
  await page.video()!.saveAs(path.join(OUT, "video-approval-click.webm"));
  await ctx.close();
  console.log("    ✓ video-approval-click.webm");
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log(`\nCapturing CodePlane screenshots → ${OUT}\n`);
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  });

  // Desktop context: 1920×1080 @ 2x = 3840×2160
  console.log("Desktop captures (1920×1080 @ 2x):");
  const desktopCtx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });
  const page = await desktopCtx.newPage();

  // Fake EventSource to prevent reconnect loops
  await page.addInitScript(() => {
    (window as any).EventSource = class FakeEventSource extends EventTarget {
      readyState = 0;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;

      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;

      constructor(url: string | URL, _init?: EventSourceInit) {
        super();
        this.url = String(url);
        queueMicrotask(() => {
          this.readyState = 1;
          const openEvt = new Event("open");
          this.onopen?.(openEvt as any);
          this.dispatchEvent(openEvt);
          // Fire snapshot with all jobs
          const snapshotData = JSON.stringify({
            jobs: (window as any).__mockJobs ?? [],
            pendingApprovals: (window as any).__mockApprovals ?? [],
          });
          const snapshotEvt = new MessageEvent("snapshot", { data: snapshotData });
          this.dispatchEvent(snapshotEvt);
          // Heartbeat
          const hb = new MessageEvent("session_heartbeat", { data: "{}" });
          this.dispatchEvent(hb);
        });
      }
      close() {
        this.readyState = 2;
      }
    } as any;
  });

  // Inject mock data for the fake EventSource to use
  await page.addInitScript(
    (data: { jobs: unknown[]; approvals: unknown[] }) => {
      (window as any).__mockJobs = data.jobs;
      (window as any).__mockApprovals = data.approvals;
    },
    { jobs: mockJobs, approvals: approvalJobApprovals },
  );

  await setupRoutes(page);

  await captureDashboard(page);
  await captureJobRunning(page);
  await captureJobDiff(page);
  await captureJobApproval(page);
  await captureAnalytics(page);
  await captureJobMetrics(page);

  await desktopCtx.close();

  // Video captures (separate contexts with recordVideo enabled)
  console.log("\nVideo captures:");
  await captureVideoJobCreation(browser);
  await captureVideoApprovalClick(browser);

  // Mobile context: 390×844 @ 3x (iPhone 14 Pro)
  console.log("\nMobile captures (390×844 @ 3x):");
  const mobileCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    colorScheme: "dark",
    isMobile: true,
    hasTouch: true,
  });
  // Apply the same init scripts to the mobile context
  const mobilePage = await mobileCtx.newPage();
  await mobilePage.addInitScript(
    (data: { jobs: unknown[]; approvals: unknown[] }) => {
      (window as any).__mockJobs = data.jobs;
      (window as any).__mockApprovals = data.approvals;
    },
    { jobs: mockJobs, approvals: approvalJobApprovals },
  );
  await mobilePage.addInitScript(() => {
    (window as any).EventSource = class FakeEventSource extends EventTarget {
      readyState = 0;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      constructor(url: string | URL, _init?: EventSourceInit) {
        super();
        this.url = String(url);
        queueMicrotask(() => {
          this.readyState = 1;
          const openEvt = new Event("open");
          this.onopen?.(openEvt as any);
          this.dispatchEvent(openEvt);
          const snapshotData = JSON.stringify({
            jobs: (window as any).__mockJobs ?? [],
            pendingApprovals: (window as any).__mockApprovals ?? [],
          });
          const snapshotEvt = new MessageEvent("snapshot", { data: snapshotData });
          this.dispatchEvent(snapshotEvt);
          const hb = new MessageEvent("session_heartbeat", { data: "{}" });
          this.dispatchEvent(hb);
        });
      }
      close() {
        this.readyState = 2;
      }
    } as any;
  });
  await setupRoutes(mobilePage);
  await mobilePage.goto(BASE);
  await mobilePage.waitForSelector('button:has-text("In Progress")', {
    timeout: 10_000,
  });
  await mobilePage.waitForTimeout(800);
  await patchConnectionBadge(mobilePage);
  await mobilePage.screenshot({
    path: path.join(OUT, "dashboard-mobile.png"),
    type: "png",
  });

  console.log("  → Job detail (mobile)");
  await mobilePage.goto(`${BASE}/jobs/customer-email-search`);
  await mobilePage.waitForSelector("text=Add customer email search", {
    timeout: 10_000,
  });
  await mobilePage.waitForTimeout(1200);
  await patchConnectionBadge(mobilePage);
  await mobilePage.screenshot({
    path: path.join(OUT, "job-mobile.png"),
    type: "png",
  });

  // Capture mobile voice input with REAL WaveSurfer waveform
  // Close the existing page and create a fresh CONTEXT with fake audio device
  console.log("  → Job detail (mobile) — voice input (real waveform)");
  await mobilePage.close();

  // Create a separate mobile context with Chromium's fake audio device
  // This provides a real sine wave MediaStream that WaveSurfer renders
  const voiceCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    colorScheme: "dark",
    isMobile: true,
    hasTouch: true,
    permissions: ["microphone"],
  });

  const voiceMobilePage = await voiceCtx.newPage();
  // Inject SSE mock
  await voiceMobilePage.addInitScript(
    (data: { jobs: unknown[]; approvals: unknown[] }) => {
      (window as any).__mockJobs = data.jobs;
      (window as any).__mockApprovals = data.approvals;
    },
    { jobs: mockJobs, approvals: approvalJobApprovals },
  );
  await voiceMobilePage.addInitScript(() => {
    (window as any).EventSource = class FakeEventSource extends EventTarget {
      readyState = 0;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      constructor(url: string | URL, _init?: EventSourceInit) {
        super();
        this.url = String(url);
        queueMicrotask(() => {
          this.readyState = 1;
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("snapshot", { data: JSON.stringify({
            jobs: (window as any).__mockJobs ?? [],
            pendingApprovals: (window as any).__mockApprovals ?? [],
          })}));
          this.dispatchEvent(new MessageEvent("session_heartbeat", { data: "{}" }));
        });
      }
      close() { this.readyState = 2; }
    } as any;
  });
  // Mock the transcribe endpoint to hang (keep recording state active)
  await voiceMobilePage.route("**/voice/transcribe", () => { /* never respond */ });
  await setupRoutes(voiceMobilePage);

  await voiceMobilePage.goto(BASE + "/jobs/customer-email-search");
  await voiceMobilePage.waitForSelector("text=Add customer email search", { timeout: 10_000 });
  await voiceMobilePage.waitForTimeout(1000);
  await patchConnectionBadge(voiceMobilePage);

  // Scroll to expose composer at bottom
  await voiceMobilePage.evaluate(() => {
    const main = document.querySelector("main");
    if (main) main.scrollTop = main.scrollHeight;
  });
  await voiceMobilePage.waitForTimeout(400);

  // Click the mic button — triggers real WaveSurfer recording
  const voiceMicBtn = voiceMobilePage.locator('button[aria-label="Voice input"]');
  if (await voiceMicBtn.isVisible()) {
    await voiceMicBtn.click();
    // Let WaveSurfer render the scrolling waveform for ~3 seconds
    await voiceMobilePage.waitForTimeout(3000);
  }

  // Check if waveform rendered — if not, inject a CSS-based fallback
  const hasWaveform = await voiceMobilePage.evaluate(() => {
    // WaveSurfer renders into a shadow DOM canvas; check for any canvas or wave element
    const canvases = document.querySelectorAll("canvas");
    for (const c of canvases) {
      if (c.width > 10 && c.height > 10) return true;
    }
    // Also check for WaveSurfer's container div
    const wsContainer = document.querySelector('[data-wavesurfer]') || document.querySelector('.wavesurfer-wrapper');
    return wsContainer !== null;
  });
  console.log("    Waveform canvas detected:", hasWaveform);

  if (!hasWaveform) {
    // Fallback: inject a realistic SVG waveform into the waveform container
    console.log("    Injecting SVG waveform fallback");
    await voiceMobilePage.evaluate(() => {
      // Find the waveform container ref div (empty div after textarea)
      const composerArea = document.querySelector('button[aria-label="Stop recording"]')?.closest(".rounded-lg.border");
      if (!composerArea) return;
      const textareaParent = composerArea.querySelector("textarea")?.parentElement;
      if (!textareaParent) return;

      // Hide the textarea and insert a full-width waveform
      const textarea = textareaParent.querySelector("textarea") as HTMLElement;
      if (textarea) {
        textarea.style.display = "none";
      }

      // Create SVG waveform that fills the parent width
      const svgNS = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(svgNS, "svg");
      const w = 800; // viewBox units — scales to fill container
      const h = 40;
      svg.setAttribute("viewBox", "0 0 " + w + " " + h);
      svg.setAttribute("width", "100%");
      svg.setAttribute("height", "40");
      svg.style.display = "block";
      svg.style.marginTop = "4px";

      // Dense bars simulating scrolling waveform
      const barW = 2;
      const gap = 1.5;
      const numBars = Math.floor(w / (barW + gap));
      for (let i = 0; i < numBars; i++) {
        const rect = document.createElementNS(svgNS, "rect");
        const x = i * (barW + gap);
        // Simulate natural speech amplitude: clusters of activity with quiet gaps
        var t = i / numBars;
        // Multiple overlapping sine waves for organic feel
        var wave1 = Math.sin(t * Math.PI * 5.3) * 0.4;
        var wave2 = Math.sin(t * Math.PI * 11.7 + 1.2) * 0.25;
        var wave3 = Math.sin(t * Math.PI * 23.1 + 0.7) * 0.15;
        var noise = Math.sin(i * 17.3) * 0.1 + Math.sin(i * 31.7) * 0.08;
        var amp = Math.abs(wave1 + wave2 + wave3 + noise) + 0.08;
        var barH = Math.max(2, Math.min(h - 2, amp * h * 1.2));
        var y = (h - barH) / 2;
        rect.setAttribute("x", String(x.toFixed(1)));
        rect.setAttribute("y", String(y.toFixed(1)));
        rect.setAttribute("width", String(barW));
        rect.setAttribute("height", String(barH.toFixed(1)));
        rect.setAttribute("rx", "1");
        var opacity = (0.35 + (barH / h) * 0.65).toFixed(2);
        rect.setAttribute("fill", "hsl(217 91% 60% / " + opacity + ")");
        svg.appendChild(rect);
      }

      // Insert a "Recording…" label
      const label = document.createElement("div");
      label.textContent = "Recording\u2026";
      label.style.cssText = "color:hsl(217 91% 60%);font-size:13px;margin-top:2px;opacity:0.7;";

      textareaParent.insertBefore(svg, textareaParent.firstChild);
      textareaParent.insertBefore(label, svg.nextSibling);
    });
    await voiceMobilePage.waitForTimeout(200);
  }

  await voiceMobilePage.screenshot({
    path: path.join(OUT, "mobile-voice-input.png"),
    type: "png",
  });
  await voiceCtx.close();

  // Capture mobile approval
  console.log("  → Job approval (mobile)");
  const approvalMobilePage = await mobileCtx.newPage();
  await approvalMobilePage.addInitScript(
    (data: { jobs: unknown[]; approvals: unknown[] }) => {
      (window as any).__mockJobs = data.jobs;
      (window as any).__mockApprovals = data.approvals;
    },
    { jobs: mockJobs, approvals: approvalJobApprovals },
  );
  await approvalMobilePage.addInitScript(() => {
    (window as any).EventSource = class FakeEventSource extends EventTarget {
      readyState = 0;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      constructor(url: string | URL, _init?: EventSourceInit) {
        super();
        this.url = String(url);
        queueMicrotask(() => {
          this.readyState = 1;
          this.dispatchEvent(new Event("open"));
          this.dispatchEvent(new MessageEvent("snapshot", { data: JSON.stringify({
            jobs: (window as any).__mockJobs ?? [],
            pendingApprovals: (window as any).__mockApprovals ?? [],
          })}));
          this.dispatchEvent(new MessageEvent("session_heartbeat", { data: "{}" }));
        });
      }
      close() { this.readyState = 2; }
    } as any;
  });
  await setupRoutes(approvalMobilePage);
  await approvalMobilePage.goto(`${BASE}/jobs/keyboard-shortcut-hints`);
  await approvalMobilePage.waitForSelector("text=Add keyboard shortcut hints", {
    timeout: 10_000,
  });
  await approvalMobilePage.waitForTimeout(1000);
  await patchConnectionBadge(approvalMobilePage);
  await approvalMobilePage.screenshot({
    path: path.join(OUT, "mobile-approval.png"),
    type: "png",
  });

  await mobileCtx.close();
  await browser.close();

  // List captures
  console.log("\n✓ Captures complete:");
  const files = fs.readdirSync(OUT);
  for (const f of files) {
    const stat = fs.statSync(path.join(OUT, f));
    console.log(`  ${f} (${(stat.size / 1024).toFixed(0)} KB)`);
  }
}

main().catch((err) => {
  console.error("Capture failed:", err);
  process.exit(1);
});
