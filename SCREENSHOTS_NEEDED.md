# Screenshots Needed for Documentation

> Drop the actual screenshots into the paths listed below. The docs already reference them
> by filename — once you replace the placeholders, everything renders automatically.

## How to Capture

1. **Run the app** with 3–4 jobs in different states (running, succeeded, failed, waiting for approval)
2. **Desktop**: Clean browser window, 1280×800 viewport, crop browser chrome, 2× retina
3. **Mobile**: Chrome DevTools → Device Toolbar → iPhone 14 Pro (393×852), 2× retina
4. **Consistency**: Use the same repos/prompts across all screenshots

---

## Desktop Screenshots

**Directory:** `docs/images/screenshots/desktop/`

| Filename | Page / View | What to Show |
|----------|-------------|-------------|
| `hero-dashboard.png` | Dashboard `/` | Kanban board with 3+ jobs across columns (In Progress, Awaiting Input, Failed). Full layout with header, hamburger menu, search. **This is the hero image for the homepage and README.** |
| `job-creation.png` | `/jobs/new` | Empty creation form — prompt textarea, repo dropdown, SDK selector, model dropdown, voice button |
| `job-creation-filled.png` | `/jobs/new` | Form filled with realistic prompt, repo selected, model chosen, ready to submit |
| `job-running-transcript.png` | `/jobs/:id` Transcript tab | Running job with assistant messages, tool call groups (collapsed + expanded), progress headline |
| `job-running-logs.png` | `/jobs/:id` Logs tab | Structured logs with mixed levels (debug/info/warn/error), level filter dropdown visible |
| `job-running-timeline.png` | `/jobs/:id` Timeline tab | Execution timeline with active + completed stages |
| `job-running-metrics.png` | `/jobs/:id` Metrics tab | Token usage bars, cost display, LLM calls, tool calls breakdown |
| `job-running-plan.png` | `/jobs/:id` Plan tab | Agent plan with done/active/pending steps |
| `job-diff-viewer.png` | `/jobs/:id` Diff tab | Multi-file diff with file list sidebar, syntax-highlighted content |
| `job-workspace.png` | `/jobs/:id` Workspace | File browser showing directory tree and file content |
| `approval-banner.png` | `/jobs/:id` with approval | Close-up of approval banner — approve/reject/trust buttons, permission request details |
| `complete-job-dialog.png` | `/jobs/:id` Complete dialog | Resolution options: merge, smart merge, create PR, discard, agent merge |
| `terminal-drawer.png` | Any page, terminal open | Terminal drawer at bottom with xterm.js, tab bar with 2+ sessions |
| `command-palette.png` | Any page, ⌘K open | Command palette overlay with search input and job results |
| `settings-page.png` | `/settings` | Settings showing repo list, SDK selection |
| `history-page.png` | `/history` | Archived jobs with search/filter |
| `voice-recording.png` | Job creation or transcript | Voice recording in progress — waveform visible, mic button red |
| `job-succeeded.png` | `/jobs/:id` | Completed job — success badge, final transcript, available actions |
| `job-failed.png` | `/jobs/:id` | Failed job — error badge, error details in transcript |
| `analytics-dashboard.png` | `/analytics` | Full analytics view — stat cards, cost trend chart, model breakdown, tool health, jobs table |

## Mobile Screenshots

**Directory:** `docs/images/screenshots/mobile/`

| Filename | Page / View | What to Show |
|----------|-------------|-------------|
| `mobile-dashboard.png` | Dashboard `/` | Tab-based job list (In Progress / Awaiting / Failed), 2–3 job cards |
| `mobile-dashboard-search.png` | Dashboard `/` | Search bar active with filtered results |
| `mobile-job-creation.png` | `/jobs/new` | Compact creation form on mobile |
| `mobile-job-transcript.png` | `/jobs/:id` | Running job transcript — messages, tool calls |
| `mobile-job-approval.png` | `/jobs/:id` | Approval banner with stacked approve/reject buttons |
| `mobile-job-diff.png` | `/jobs/:id` Diff tab | Scrollable syntax-highlighted diff |
| `mobile-terminal.png` | Terminal open | Terminal drawer maximized (90vh) |
| `mobile-settings.png` | `/settings` | Settings page on mobile |
| `mobile-voice.png` | Voice recording | Waveform on mobile |
| `mobile-complete-dialog.png` | Complete dialog | Merge/PR/discard dialog on mobile |

## Architecture Diagrams (SVG — create or generate)

**Directory:** `docs/images/`

| Filename | Content |
|----------|---------|
| `architecture-overview.svg` | Full system diagram: Browser → Tunnels → FastAPI → SQLite/Git/SDKs/Whisper |
| `job-state-machine.svg` | State transitions: queued → running → succeeded/failed/canceled with all edges |
| `event-flow.svg` | Domain Event → Event Bus → SSE Manager → Browser |
| `approval-flow.svg` | Approval request → operator decision → agent continues |

---

**Total: 20 desktop + 10 mobile + 4 diagrams = 34 images**
