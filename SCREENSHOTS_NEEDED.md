# Docs Asset Checklist

Internal planning file. Tracks every image and GIF needed across the docs,
README, and GitHub repo page.

## Current State

All existing screenshots under `docs/images/screenshots/` are **1×1 px placeholders**.
The docs audit consolidated pages, so only 3 images are currently referenced:

| File | Referenced by |
|------|---------------|
| `hero-dashboard.png` | `index.md`, `README.md` |
| `job-running-transcript.png` | `index.md`, `quick-start.md` |
| `job-diff-viewer.png` | `quick-start.md` |

Everything else in the screenshots directories is unreferenced and has been deleted.
New assets should only be created when a doc page is wired to use them.

## Capture Standard

1. Run the app with realistic seeded data: 1 running job, 1 in-review, 1 completed, 1 pending approval.
2. Desktop: **1280×800** viewport, crop browser chrome, **2× retina** export.
3. Mobile: **iPhone 14 Pro** viewport via DevTools, 2× export.
4. GIFs: max **15 seconds**, **12 fps**, 800 px wide (use `gifski` or ScreenToGif for quality).
5. Keep repo names, prompts, branch names consistent across all captures.
6. Prefer full-screen product scenes over cropped fragments.

---

## Tier 1 — Blocking (currently referenced, broken)

These 3 replace existing placeholder references. Without them, live doc pages display blank.

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Type | Docs page | What to capture |
|-------|------|-----------|-----------------|
| `hero-dashboard.png` | Screenshot | index.md, README | Dashboard with 4–5 jobs in mixed states (running, review, completed, failed). Fill the card grid. This is the anchor visual. |
| `job-running-transcript.png` | Screenshot | index.md, quick-start.md | Active job detail view. Transcript tab selected, agent reasoning visible, tool call group expanded, cost/token counters in the sidebar. |
| `job-diff-viewer.png` | Screenshot | quick-start.md | Diff tab with file tree open, multi-file changes, syntax highlighting readable. Pick a diff with both additions and deletions. |

---

## Tier 2 — High-value additions to wire into docs

These don't have doc references yet. Each entry includes where to add the reference once captured.

### GIFs (interaction-heavy features)

GIFs are the right format here because the value is seeing the *flow*, not a single frame.

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Docs page | What to capture | Why GIF |
|-------|-----------|-----------------|---------|
| `create-job-flow.gif` | guide.md § Creating Jobs | Open New Job → type prompt → select repo/SDK/model → submit → job starts. 10–12 seconds. | Shows the whole creation UX is 3 clicks. |
| `approval-flow.gif` | guide.md § Approvals | Agent running → approval banner appears → click Approve → agent resumes. | The pause-approve-resume loop is the trust story. Static screenshot loses the drama. |
| `merge-resolve.gif` | guide.md § Merging | Job in review → click Complete → choose Smart Merge → see success. | Multiple options in one modal; animation shows the decision flow naturally. |
| `transcript-streaming.gif` | guide.md § Transcript | Agent actively working, transcript entries appearing live, tool call group auto-expanding. 8–10 seconds. | The streaming feel is the core product experience. A still image can't convey real-time. |
| `command-palette.gif` | guide.md § Command Palette | Open palette → type query → results filter live → navigate to job. | Instant search UX is best shown in motion. |

### Screenshots (information-dense/static features)

**Directory:** `docs/images/screenshots/desktop/`

| Asset | Docs page | What to capture |
|-------|-----------|-----------------|
| `analytics-dashboard.png` | guide.md § Analytics | Scorecard + model comparison + cost trend chart. All three panels visible. |
| `settings-page.png` | configuration.md | Settings screen with at least 2 registered repos, SDK/model defaults visible, permission mode selector. |
| `approval-banner.png` | guide.md § Approvals (fallback still) | Clear approval request: shows file path, action type, approve/reject/trust buttons. For pages where GIF autoplay is undesirable. |
| `terminal-drawer.png` | guide.md § Terminal | Terminal open at bottom, 2 tabs (global + job-specific), useful output visible. |

### Mobile

**Directory:** `docs/images/screenshots/mobile/`

| Asset | Docs page | What to capture |
|-------|-----------|-----------------|
| `mobile-dashboard.png` | index.md (mobile callout), guide.md § Remote Access | Dashboard with active jobs, stacked card layout. |
| `mobile-job-transcript.png` | guide.md § Remote Access | Running job transcript in compact mobile layout, agent activity visible. |
| `mobile-approval.png` | guide.md § Remote Access | Approval prompt with tap targets clearly visible. |
| `mobile-voice-input.gif` | guide.md § Voice Input / Remote Access | GIF (~5 sec): tap mic → waveform visualizer animates → tap stop → transcribed text appears in textarea. The scrolling waveform on a phone screen is visually striking and impossible to convey with a still image. |

---

## Tier 3 — Nice to have

Capture only if a page reads badly without them. Don't block a release on these.

| Asset | Type | Docs page | Notes |
|-------|------|-----------|-------|
| `job-creation-filled.png` | Screenshot | quick-start.md | Could also just link to the GIF. |
| `plan-tab.png` | Screenshot | guide.md § Plan | Step list with mixed ✅/🔄/⏳ states. |
| `metrics-tab.png` | Screenshot | guide.md § Metrics | Token/cost chart mid-job. |
| `mobile-merge.png` | Screenshot (mobile) | guide.md § Remote Access | Merge controls in stacked layout. |

---

## Not Needed

Explicitly deferred — don't capture these unless a doc page is added that requires them.

- Empty/blank state screenshots (onboarding wizard handles this)
- Separate logs and timeline tab captures (text descriptions suffice)
- History page (one line of docs, no visual needed)
- Architecture diagrams beyond the existing ASCII art (it's clear enough)
- Per-SDK setup screenshots (SDK docs handle their own onboarding)

---

## Completion Checklist

- [ ] **Tier 1** captured and replacing placeholders — docs pages render correctly
- [ ] **Tier 2 GIFs** captured and wired into guide.md with `![alt](path){ loading=lazy }`
- [ ] **Tier 2 screenshots** captured and wired into guide.md / configuration.md
- [ ] **Mobile shots** captured and added to remote access section
- [ ] README hero image renders on GitHub (use relative path `docs/images/screenshots/desktop/hero-dashboard.png`)
- [ ] All GIFs under 2 MB (compress with `gifsicle -O3` if needed)
- [ ] No remaining 1×1 placeholder PNGs in the repo
