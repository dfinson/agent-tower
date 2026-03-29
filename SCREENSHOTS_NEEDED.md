# Docs Asset Checklist

Internal planning file. Tracks every image and GIF needed across the docs,
README, and GitHub repo page — plus the setup procedure to create realistic
volume for the captures.

## Current State

All existing screenshots under `docs/images/screenshots/` are **1×1 px placeholders**.
Only 3 images are currently referenced by live docs:

| File | Referenced by |
|------|---------------|
| `hero-dashboard.png` | `index.md`, `README.md` |
| `job-running-transcript.png` | `index.md`, `quick-start.md` |
| `job-diff-viewer.png` | `quick-start.md` |

Everything else was deleted. New assets get created when a doc page is wired
to use them.

---

## Capture Setup

The dashboard needs to look like a real operator's workspace, not a toy with 2 jobs.
We use the two demo repos: **demo-issue-tracker-api** (Python/FastAPI) and
**demo-support-dashboard** (React/TS/Vite), both already registered in CodePlane.

### Target scene: 10–12 concurrent/recent jobs across both repos, mixed SDKs

**Create in this order** so the dashboard fills up naturally and states layer:

| # | Repo | SDK | Prompt | Target state | Notes |
|---|------|-----|--------|--------------|-------|
| 1 | demo-issue-tracker-api | copilot | "Add input validation to the create ticket endpoint and cover it with tests" | **completed** → archive | Provides diff content for diff viewer shot |
| 2 | demo-support-dashboard | claude | "Add inline validation to the create ticket form with error messages" | **completed** | Shows Claude SDK in the mix |
| 3 | demo-issue-tracker-api | copilot | "Exclude archived tickets from the default list response and update the OpenAPI docs" | **review** | Stays in review for merge GIF |
| 4 | demo-support-dashboard | copilot | "Fix ticket search so it matches customer email as well as subject" | **completed** → archive | Background volume |
| 5 | demo-issue-tracker-api | claude | "Tighten error handling around ticket archival — return proper 404/409 codes" | **review** | Second review-state job visible on dashboard |
| 6 | demo-support-dashboard | copilot | "Persist the selected status filter in the URL query string" | **running** | Live job #1 for transcript streaming capture |
| 7 | demo-issue-tracker-api | copilot | "Add customer email search to the ticket list endpoint and add tests" | **running** | Live job #2 — shows concurrent execution |
| 8 | demo-support-dashboard | claude | "Improve the empty state copy and illustration for filtered results with zero matches" | **running** (approval_required) | Triggers approval banner for capture |
| 9 | demo-issue-tracker-api | copilot | "Add pagination to the ticket list endpoint with limit/offset query params" | **queued** | Shows queue when at capacity |
| 10 | demo-support-dashboard | copilot | "Add a loading skeleton to the ticket list while the API request is in flight" | **queued** | Second queued job |

**State distribution on dashboard at capture time:**
- 2 running + 1 paused (approval) — active work
- 2 queued — shows capacity management
- 2 in review — pending operator decisions
- 2 completed (not yet archived) — recent finishes
- 1–2 archived — visible in history

This gives us a full, realistic dashboard with **10+ jobs across 2 repos, 2 SDKs, 4+ states**.

### Settings for captures

```yaml
max_concurrent_jobs: 3         # so queuing is visible
permission_mode: auto          # default; override per-job for approval shots
```

### Capture sequence

1. Create jobs 1–2, let them complete, archive job 1
2. Create jobs 3–5, let 3 and 5 land in review, let 4 complete and archive
3. Set job 8 to `permission_mode: approval_required`
4. Create jobs 6, 7, 8 — they'll run concurrently (max_concurrent=3)
5. Create jobs 9, 10 while 6–8 are running — they'll queue
6. **Capture dashboard hero** now (all 10 jobs visible, mixed states)
7. Click into job 6 or 7 → **capture transcript streaming GIF**
8. Wait for job 8's approval prompt → **capture approval GIF/screenshot**
9. Click into completed job 1's diff → **capture diff viewer**
10. After jobs finish, **capture analytics** (will have real cost/model data from 10+ jobs)
11. Switch to mobile viewport, **capture mobile shots**
12. Open settings → **capture settings** (2 repos registered, SDK defaults)
13. Open command palette, search → **capture command palette GIF**
14. Click Complete on job 3 → **capture merge GIF**

---

## Capture Standard

1. Desktop: **1280×800** viewport, crop browser chrome, **2× retina** export.
2. Mobile: **iPhone 14 Pro** viewport via DevTools, 2× export.
3. GIFs: max **15 seconds**, **12 fps**, 800 px wide (use `gifski` or ScreenToGif for quality).
4. Keep prompts, repo names, branch names consistent — use exactly the prompts above.
5. Prefer full-screen product scenes over cropped fragments.

---

## Tier 1 — Blocking (currently referenced, broken)

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Type | Docs page | What to capture |
|-------|------|-----------|-----------------|
| `hero-dashboard.png` | Screenshot | index.md, README | Dashboard at step 6 above — 10+ jobs, mixed states, both repos visible in cards. Fill the grid. This is the anchor visual. |
| `job-running-transcript.png` | Screenshot | index.md, quick-start.md | Active job (job 6 or 7). Transcript tab, agent reasoning visible, tool call group expanded, cost/token sidebar. |
| `job-diff-viewer.png` | Screenshot | quick-start.md | Completed job 1 diff tab. File tree open, multi-file changes, syntax highlighting. Pick a file with both additions and deletions. |

---

## Tier 2 — High-value additions to wire into docs

### GIFs (interaction-heavy features)

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Docs page | What to capture | Why GIF |
|-------|-----------|-----------------|---------|
| `create-job-flow.gif` | guide.md § Creating Jobs | Create job 9 or 10 — open New Job → type prompt → select repo/SDK/model → submit → see it queue. 10–12 sec. | Shows the whole creation UX is 3 clicks. |
| `approval-flow.gif` | guide.md § Approvals | Job 8 running → approval banner appears → click Approve → agent resumes. | The pause-approve-resume loop is the trust story. |
| `merge-resolve.gif` | guide.md § Merging | Job 3 in review → click Complete → choose Smart Merge → success. | Decision flow with multiple options. |
| `transcript-streaming.gif` | guide.md § Transcript | Job 6 or 7 actively working. Entries appearing live, tool call group auto-expanding. 8–10 sec. | Core product feel — real-time streaming. |
| `command-palette.gif` | guide.md § Command Palette | Open palette → type "ticket" → jobs filter by prompt → navigate to one. | Instant search UX. |

### Screenshots (information-dense/static)

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Docs page | What to capture |
|-------|-----------|-----------------|
| `analytics-dashboard.png` | guide.md § Analytics | After all 10 jobs have run — scorecard, model comparison (copilot vs claude), cost trend. Real data from real runs. |
| `settings-page.png` | configuration.md | Settings: both demo repos registered, SDK defaults, permission mode selector visible. |
| `approval-banner.png` | guide.md § Approvals (still fallback) | Job 8's approval request: file path, action type, approve/reject/trust buttons. |
| `terminal-drawer.png` | guide.md § Terminal | Terminal with 2 tabs (global + job-specific for job 6), real output. |

### Mobile

**Directory:** `docs/images/screenshots/mobile/`

| Asset | Docs page | What to capture |
|-------|-----------|-----------------|
| `mobile-dashboard.png` | index.md, guide.md § Remote Access | Same scene as hero — 10+ jobs visible in stacked card layout. |
| `mobile-job-transcript.png` | guide.md § Remote Access | Job 6 or 7 transcript in compact mobile layout. |
| `mobile-approval.png` | guide.md § Remote Access | Job 8's approval prompt with visible tap targets. |
| `mobile-voice-input.gif` | guide.md § Voice Input / Remote Access | GIF (~5 sec): tap mic → waveform animates → tap stop → text appears. |

---

## Tier 3 — Nice to have

| Asset | Type | Docs page | Notes |
|-------|------|-----------|-------|
| `job-creation-filled.png` | Screenshot | quick-start.md | Could link to the GIF instead. |
| `plan-tab.png` | Screenshot | guide.md § Plan | Step list with mixed states. |
| `metrics-tab.png` | Screenshot | guide.md § Metrics | Token/cost chart mid-job. |
| `mobile-merge.png` | Screenshot (mobile) | guide.md § Remote Access | Merge controls stacked. |

---

## Not Needed

- Empty/blank state screenshots
- Separate logs and timeline tab captures
- History page screenshot
- Architecture diagrams beyond existing ASCII art
- Per-SDK setup screenshots

---

## Completion Checklist

- [ ] Demo repos reset to clean main branches before capture session
- [ ] **Tier 1** captured and replacing placeholders — docs pages render
- [ ] **Tier 2 GIFs** captured and wired into guide.md
- [ ] **Tier 2 screenshots** captured and wired into guide.md / configuration.md
- [ ] **Mobile shots** captured and added to remote access section
- [ ] README hero image renders on GitHub
- [ ] All GIFs under 2 MB (compress with `gifsicle -O3` if needed)
- [ ] No remaining 1×1 placeholder PNGs in the repo
- [ ] Analytics screenshot shows real cost data from 10+ jobs across both SDKs
