/**
 * Screenshot capture tool for CodePlane docs.
 *
 * Hits the REAL running backend (default http://localhost:8080).
 * Creates 2 short real jobs for "running" state shots, then cancels them.
 * Mocks only approval data (no real approval jobs exist).
 * Uses fake microphone for the wavesurf voice-input screenshot.
 *
 * Usage:
 *   cd demo-video && npx tsx capture/capture-screenshots.ts
 *   CAPTURE_BASE=http://localhost:8080 npx tsx capture/capture-screenshots.ts
 *
 * Output: docs/images/screenshots/desktop/ and docs/images/screenshots/mobile/
 */

import { chromium, type BrowserContext, type Page } from "playwright";
import * as path from "path";
import * as fs from "fs";

const BASE = process.env.CAPTURE_BASE ?? "http://localhost:8080";
const REPO_ROOT = path.resolve(__dirname, "../..");
const OUT_DESKTOP = path.join(REPO_ROOT, "docs/images/screenshots/desktop");
const OUT_MOBILE = path.join(REPO_ROOT, "docs/images/screenshots/mobile");

const DESKTOP_VP = { width: 1440, height: 900 };
const MOBILE_VP = { width: 390, height: 844 };

// A review-state job with good transcript + diff data
const REVIEW_JOB_ID = "add-metrics-endpoint";
// A completed job with nice transcript
const COMPLETED_JOB_ID = "comprehensive-refactor";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function shot(page: Page, dest: string, clip?: { x: number; y: number; width: number; height: number }) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  await page.screenshot({ path: dest, fullPage: !clip, clip });
  console.log("  ✓", path.relative(REPO_ROOT, dest));
}

async function disableAnimations(page: Page) {
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-delay: 0ms !important;
        transition-duration: 0.001ms !important;
        transition-delay: 0ms !important;
      }
    `,
  });
}

async function waitForApp(page: Page) {
  // SSE connections prevent networkidle from ever resolving — use a short cap
  await page.waitForLoadState("networkidle", { timeout: 2_500 }).catch(() => {});
  await page.waitForTimeout(800);
}

async function createJob(repo: string, prompt: string): Promise<string> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8_000);
  try {
    const res = await fetch(`${BASE}/api/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo, prompt, sdk: "copilot" }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`Failed to create job: ${res.status} ${await res.text()}`);
    const data = (await res.json()) as { id: string };
    return data.id;
  } catch (err) {
    clearTimeout(timeoutId);
    throw err;
  }
}

async function cancelJob(jobId: string) {
  await fetch(`${BASE}/api/jobs/${jobId}/cancel`, { method: "POST" }).catch(() => {});
}

async function waitForState(jobId: string, states: string[], timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${BASE}/api/jobs/${jobId}`);
    if (res.ok) {
      const job = (await res.json()) as { state: string };
      if (states.includes(job.state)) return job.state;
      if (["completed", "failed", "canceled"].includes(job.state)) return job.state;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Timeout waiting for job ${jobId} to reach ${states.join("/")}`);
}

// ---------------------------------------------------------------------------
// Approval mock: directly inject an approval_requested event into the Zustand
// store via window.__codeplane_store (exposed in dev builds). This is
// deterministic and avoids races with the global SSE snapshot that would
// otherwise wipe the injected approval.
// ---------------------------------------------------------------------------

async function injectApproval(page: Page) {
  const payload = {
    approvalId: "approval-001",
    jobId: REVIEW_JOB_ID,
    description: "Push feature branch to remote repository",
    proposedAction: "Push 3 commits to origin/cpl/add-metrics-endpoint",
    requiresExplicitApproval: true,
    // Use an early timestamp so buildFeedItems inserts this approval
    // at the VERY START of the transcript feed (before any real entries).
    // This makes it visible at the top without needing to scroll.
    timestamp: "2020-01-01T00:00:00.000Z",
  };
  await page.evaluate((data) => {
    const store = (window as unknown as Record<string, { getState: () => { dispatchSSEEvent: (t: string, d: unknown) => void } }>)["__codeplane_store"];
    if (store) {
      store.getState().dispatchSSEEvent("approval_requested", data);
    }
  }, payload);
}

// ---------------------------------------------------------------------------
// Analytics helper — single navigation, scroll to each section
// ---------------------------------------------------------------------------

async function captureAnalyticsSections(page: Page, outDir: string) {
  await page.goto(`${BASE}/analytics`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 3_000 }).catch(() => {});
  // "Cost Trend" is a non-conditional h2 that only appears after data loads
  await page.waitForSelector('h2:has-text("Cost Trend")', { timeout: 8_000 }).catch(() => {});
  await page.waitForTimeout(600);
  await disableAnimations(page);

  // 1. Dashboard overview — top of page (Budget + Activity cards visible)
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await shot(page, path.join(outDir, "analytics-dashboard.png"));

  // 2. Scorecard — same area (Budget + Activity = the scorecard)
  await shot(page, path.join(outDir, "analytics-scorecard.png"));

  // 3. Model Comparison
  const modelH2 = page.locator("h2").filter({ hasText: "Model Comparison" }).first();
  await modelH2.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -30));
  await page.waitForTimeout(300);
  await shot(page, path.join(outDir, "analytics-model-comparison.png"));

  // 4. Repository Breakdown
  const repoH2 = page.locator("h2").filter({ hasText: "Repository Breakdown" }).first();
  await repoH2.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -30));
  await page.waitForTimeout(300);
  await shot(page, path.join(outDir, "analytics-repo-breakdown.png"));

  // 5. Tool Health — expand the CollapsibleSection, then scroll to it
  const toolHealthBtn = page
    .locator("button")
    .filter({ has: page.locator("h2").filter({ hasText: "Tool Health" }) });
  await toolHealthBtn.scrollIntoViewIfNeeded();
  await toolHealthBtn.click().catch(() => {});
  await page.waitForTimeout(500);
  const toolHealthH2 = page.locator("h2").filter({ hasText: "Tool Health" }).first();
  await toolHealthH2.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -30));
  await page.waitForTimeout(300);
  await shot(page, path.join(outDir, "analytics-tool-health.png"));

  // 6. Cost Drivers — expand CollapsibleSection (only shown when data exists)
  const costDriversBtn = page
    .locator("button")
    .filter({ has: page.locator("h2").filter({ hasText: "Cost Drivers" }) });
  const costDriversVisible = await costDriversBtn.isVisible({ timeout: 2_000 }).catch(() => false);
  if (costDriversVisible) {
    await costDriversBtn.scrollIntoViewIfNeeded();
    await costDriversBtn.click().catch(() => {});
    await page.waitForTimeout(500);
    const costH2 = page.locator("h2").filter({ hasText: "Cost Drivers" }).first();
    await costH2.scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -30));
    await page.waitForTimeout(300);
  } else {
    // No cost driver data — scroll to bottom to show what's there
    console.log("  Note: Cost Drivers section not visible, screenshotting bottom of page");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(300);
  }
  await shot(page, path.join(outDir, "analytics-cost-drivers.png"));
}

// ---------------------------------------------------------------------------
// Desktop captures
// ---------------------------------------------------------------------------

async function captureDesktop(context: BrowserContext, liveJobId: string) {
  console.log("\nDesktop captures (1440×900)…");
  const page = await context.newPage();
  await page.setViewportSize(DESKTOP_VP);

  // 1. Hero dashboard
  console.log(" [dashboard]");
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await shot(page, path.join(OUT_DESKTOP, "hero-dashboard.png"));

  // 2. Job detail — review state with transcript
  console.log(" [job-running-transcript]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  // Show transcript tab (usually default)
  await page.getByRole("tab", { name: /transcript/i }).click().catch(() => {});
  await page.waitForTimeout(400);
  await shot(page, path.join(OUT_DESKTOP, "job-running-transcript.png"));

  // 3. Diff viewer — same job, diff tab
  console.log(" [job-diff-viewer]");
  await page.getByRole("tab", { name: /changes|diff/i }).click().catch(() => {});
  await page.waitForTimeout(600);
  await shot(page, path.join(OUT_DESKTOP, "job-diff-viewer.png"));

  // 4. Approval banner — inject at start of transcript feed
  console.log(" [approval-banner]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  // Inject with early timestamp — appears before all real entries at top of feed
  await injectApproval(page);
  await page.waitForTimeout(600);
  await shot(page, path.join(OUT_DESKTOP, "approval-banner.png"));

  // 5. Metrics tab
  console.log(" [metrics-tab]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await page.getByRole("tab", { name: /metrics|cost/i }).click().catch(() => {});
  await page.waitForTimeout(400);
  await shot(page, path.join(OUT_DESKTOP, "metrics-tab.png"));

  // 6. Live running job transcript
  if (liveJobId) {
    console.log(" [transcript-streaming — live job]");
    await page.goto(`${BASE}/jobs/${liveJobId}`, { waitUntil: "domcontentloaded" });
    await waitForApp(page);
    await disableAnimations(page);
    await page.getByRole("tab", { name: /transcript/i }).click().catch(() => {});
    await page.waitForTimeout(800);
    await shot(page, path.join(OUT_DESKTOP, "transcript-streaming.png"));
  }

  // 7–12. Analytics sections (single-page scroll, no tabs)
  console.log(" [analytics]");
  await captureAnalyticsSections(page, OUT_DESKTOP);

  await page.close();
}

// ---------------------------------------------------------------------------
// Mobile captures
// ---------------------------------------------------------------------------

async function captureMobile(context: BrowserContext, liveJobId: string) {
  console.log("\nMobile captures (390×844)…");
  const page = await context.newPage();
  await page.setViewportSize(MOBILE_VP);

  // 1. Hero dashboard
  console.log(" [hero-dashboard]");
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await shot(page, path.join(OUT_MOBILE, "hero-dashboard.png"));

  // 2. Job transcript (review job)
  console.log(" [job-transcript]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await page.getByRole("tab", { name: /transcript/i }).click().catch(() => {});
  await page.waitForTimeout(400);
  await shot(page, path.join(OUT_MOBILE, "job-transcript.png"));

  // 3. Mobile approval banner — inject at start of transcript feed
  console.log(" [approval-banner]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await injectApproval(page);
  await page.waitForTimeout(600);
  await shot(page, path.join(OUT_MOBILE, "approval-banner.png"));

  // 4. Mobile transcript streaming (live job)
  if (liveJobId) {
    console.log(" [transcript-streaming — live job]");
    await page.goto(`${BASE}/jobs/${liveJobId}`, { waitUntil: "domcontentloaded" });
    await waitForApp(page);
    await disableAnimations(page);
    await page.getByRole("tab", { name: /transcript/i }).click().catch(() => {});
    await page.waitForTimeout(800);
    await shot(page, path.join(OUT_MOBILE, "transcript-streaming.png"));
  }

  // 5. Mobile voice input — fake mic, click record button
  console.log(" [voice-input]");
  await page.goto(`${BASE}/jobs/new`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);

  // Inject fake getUserMedia so WaveSurfer's RecordPlugin doesn't fail
  await page.addInitScript(() => {
    const silence = () => {
      const AudioContext = (window as unknown as { AudioContext: typeof globalThis.AudioContext }).AudioContext
        || (window as unknown as { webkitAudioContext: typeof globalThis.AudioContext }).webkitAudioContext;
      if (!AudioContext) return new MediaStream();
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const dst = osc.connect(ctx.createMediaStreamDestination()) as MediaStreamAudioDestinationNode;
      osc.start();
      return dst.stream;
    };
    Object.defineProperty(navigator, "mediaDevices", {
      writable: true,
      value: {
        getUserMedia: async () => silence(),
        enumerateDevices: async () => [],
      },
    });
  });

  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);

  // Click the mic button to start recording
  const micBtn = page.getByRole("button", { name: /record|microphone|voice|mic/i });
  if (await micBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await micBtn.click();
    await page.waitForTimeout(1200); // let waveform initialize and animate
    await shot(page, path.join(OUT_MOBILE, "voice-input.png"));
    // Stop recording
    await micBtn.click().catch(() => {});
  } else {
    // Fallback: screenshot job creation without recording state
    await shot(page, path.join(OUT_MOBILE, "voice-input.png"));
  }

  // 6. Mobile voice input for desktop too
  console.log(" [voice-input desktop]");
  await page.setViewportSize(DESKTOP_VP);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  const micBtn2 = page.getByRole("button", { name: /record|microphone|voice|mic/i });
  if (await micBtn2.isVisible({ timeout: 3000 }).catch(() => false)) {
    await micBtn2.click();
    await page.waitForTimeout(1200);
    await shot(page, path.join(OUT_MOBILE, "mobile-voice-input.png"));
    await micBtn2.click().catch(() => {});
  }

  // 7. Mobile job diff
  console.log(" [job-diff-viewer]");
  await page.setViewportSize(MOBILE_VP);
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await page.getByRole("tab", { name: /changes|diff/i }).click().catch(() => {});
  await page.waitForTimeout(600);
  await shot(page, path.join(OUT_MOBILE, "job-diff-viewer.png"));

  // 8. Mobile approval — inject at start of transcript feed
  console.log(" [mobile-approval]");
  await page.goto(`${BASE}/jobs/${REVIEW_JOB_ID}`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  await injectApproval(page);
  await page.waitForTimeout(600);
  await shot(page, path.join(OUT_MOBILE, "mobile-approval.png"));

  // 9–14. Mobile analytics sections
  console.log(" [mobile analytics]");
  await captureAnalyticsSections(page, OUT_MOBILE);

  await page.close();
}

// ---------------------------------------------------------------------------
// Create-job flow GIF (simple: open /jobs/new, type a prompt, screenshot)
// ---------------------------------------------------------------------------

async function captureCreateJobFlow(context: BrowserContext) {
  console.log("\nCreate-job flow screenshot…");
  const page = await context.newPage();
  await page.setViewportSize(DESKTOP_VP);
  await page.goto(`${BASE}/jobs/new`, { waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);

  // Type a realistic prompt into the textarea
  const textarea = page.locator("textarea").first();
  if (await textarea.isVisible({ timeout: 3000 }).catch(() => false)) {
    await textarea.click();
    await page.keyboard.type(
      "Add input validation to the create ticket endpoint — reject blank titles, " +
        "invalid priority values, and titles over 200 chars. Return 422 with details. Cover it with tests.",
      { delay: 0 },
    );
    await page.waitForTimeout(300);
  }
  await shot(page, path.join(OUT_DESKTOP, "create-job-flow.png"));

  // Mobile
  await page.setViewportSize(MOBILE_VP);
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForApp(page);
  await disableAnimations(page);
  const m = page.locator("textarea").first();
  if (await m.isVisible({ timeout: 3000 }).catch(() => false)) {
    await m.click();
    await page.keyboard.type("Add input validation to the create ticket endpoint", { delay: 0 });
    await page.waitForTimeout(300);
  }
  await shot(page, path.join(OUT_MOBILE, "create-job-flow.png"));

  await page.close();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log(`\nCapturing CodePlane screenshots → docs/images/screenshots/`);
  console.log(`Backend: ${BASE}\n`);

  // Create 2 short real jobs so the dashboard shows a "running" state
  console.log("Creating real jobs for running-state screenshots…");
  const jobId1 = await createJob(
    "/home/dave01/wsl-repos/codeplane-demos/demo-issue-tracker-api",
    "Add a GET /ping endpoint that returns {\"pong\": true}. One line change.",
  ).catch((e) => { console.error("  Warning: job 1 creation failed:", e.message); return ""; });
  if (jobId1) console.log("  Created job:", jobId1);

  const jobId2 = await createJob(
    "/home/dave01/wsl-repos/codeplane-demos/demo-support-dashboard",
    "Add a console.log('app started') to the main entry file.",
  ).catch((e) => { console.error("  Warning: job 2 creation failed:", e.message); return ""; });
  if (jobId2) console.log("  Created job:", jobId2);

  // Wait for at least one job to be running/queued (not instant)
  let liveJobId = "";
  if (jobId1) {
    console.log("  Waiting for job to enter running/queued state…");
    const state = await waitForState(jobId1, ["running", "queued"], 20_000).catch(() => "unknown");
    console.log("  Job state:", state);
    if (["running", "queued"].includes(state)) liveJobId = jobId1;
  }

  // Launch browser with fake microphone support
  const browser = await chromium.launch({
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  });

  try {
    // Desktop context
    const desktopCtx = await browser.newContext({
      permissions: ["microphone"],
    });
    await captureDesktop(desktopCtx, liveJobId);
    await captureCreateJobFlow(desktopCtx);
    await desktopCtx.close();

    // Mobile context
    const mobileCtx = await browser.newContext({
      permissions: ["microphone"],
    });
    await captureMobile(mobileCtx, liveJobId);
    await mobileCtx.close();
  } finally {
    await browser.close();

    // Cancel the test jobs
    const toCancel = [jobId1, jobId2].filter(Boolean);
    if (toCancel.length) {
      console.log("\nCanceling test jobs…");
      for (const id of toCancel) {
        await cancelJob(id);
        console.log("  Canceled:", id);
      }
    }
  }

  console.log("\nDone.");
}

main().catch((err) => {
  console.error("Capture failed:", err);
  process.exit(1);
});
