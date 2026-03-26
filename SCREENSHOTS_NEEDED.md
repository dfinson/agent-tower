# Docs Asset Checklist

Internal planning file for the minimum image set needed to make the docs look credible without turning screenshots into a second project.

## Goal

Show the product clearly with a small set of high-signal assets:

- one strong hero shot
- one running job shot
- one review/diff shot
- one analytics shot
- one settings or setup shot
- one mobile shot

Everything else is optional unless a page is unreadable without it.

## Capture Standard

1. Run the app with realistic seeded data: at least one running job, one completed job, and one approval event.
2. Desktop: 1280x800 viewport, cropped browser chrome, 2x scale.
3. Mobile: iPhone 14 Pro viewport in DevTools, 2x scale.
4. Keep prompts, repo names, and job titles consistent across captures.
5. Prefer complete product scenes over cropped UI fragments.

## Priority 1: Must Have

These are enough to support the home page, quick start, and core workflow pages.

**Directory:** `docs/images/screenshots/desktop/`

| Filename | Primary Use | What to Show |
|----------|-------------|-------------|
| `hero-dashboard.png` | Home page, README | Main dashboard with multiple jobs in different states. This is the anchor visual. |
| `job-running-transcript.png` | Home page, Monitoring docs | Active job with transcript, progress, and visible agent activity. |
| `job-diff-viewer.png` | Code Review docs | Multi-file diff with file tree and readable syntax highlighting. |
| `analytics-dashboard.png` | Analytics docs | Cost, usage, and model/tool breakdown in one convincing view. |
| `settings-page.png` | Quick start, configuration docs | Repository registration and core settings visible. |

**Directory:** `docs/images/screenshots/mobile/`

| Filename | Primary Use | What to Show |
|----------|-------------|-------------|
| `mobile-dashboard.png` | Home page, remote access docs | Mobile dashboard with active jobs in a believable operator view. |

## Priority 2: Nice to Have

Capture these only if they materially improve a page.

**Directory:** `docs/images/screenshots/desktop/`

| Filename | Primary Use | What to Show |
|----------|-------------|-------------|
| `job-creation-filled.png` | Creating Jobs docs | Realistic prompt, repo, SDK, and model selected. |
| `approval-banner.png` | Approvals docs | Clear approval request with approve/reject/trust controls. |
| `complete-job-dialog.png` | Merging docs | Merge, smart merge, PR, and discard actions in one modal. |
| `terminal-drawer.png` | Terminal docs | Terminal open with multiple tabs and useful command output. |
| `command-palette.png` | Command Palette docs | Search overlay with real navigation results. |

**Directory:** `docs/images/screenshots/mobile/`

| Filename | Primary Use | What to Show |
|----------|-------------|-------------|
| `mobile-job-transcript.png` | Monitoring docs | Running job transcript in compact mobile layout. |
| `mobile-job-approval.png` | Approvals docs | Approval controls in a stacked mobile layout. |

## Defer Unless Needed

Do not spend time on exhaustive tab-by-tab captures unless a page genuinely needs them.

- empty job creation form
- separate logs, timeline, metrics, and plan screenshots
- success and failure end-state screenshots
- history page screenshot
- voice recording screenshot
- dashboard search screenshot
- full architecture diagram backlog beyond one diagram with a clear docs use

## Completion Standard

The docs are in good shape when:

- the home page has a strong hero plus one or two supporting shots
- the core workflow pages have enough visuals to prove the product is real
- no page feels dependent on a screenshot to explain basic behavior
- we are not carrying a long public-facing image TODO list in the docs tree
