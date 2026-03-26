# Screenshot & Image Guide

> **This file tracks all images needed for the documentation site.**
> Once you drop in the actual screenshots, the docs will render them automatically —
> all `img` tags and markdown references are already in place using these exact filenames.

---

## Desktop Screenshots (1280×800 viewport, 2× retina)

**Directory:** `docs/images/screenshots/desktop/`

| # | Filename | Where Used | What to Capture |
|---|----------|-----------|-----------------|
| D1 | `hero-dashboard.png` | Home page, README.md | **Kanban board** with 3+ jobs across columns (In Progress, Awaiting Input, Failed). Full layout with header, nav, search bar. **This is the hero image.** |
| D2 | `job-creation.png` | Creating Jobs guide | Empty job creation form — prompt textarea, repo dropdown, SDK selector, model dropdown, voice button visible |
| D3 | `job-creation-filled.png` | Creating Jobs guide | Form filled with a realistic prompt, repo selected, model chosen, ready to submit |
| D4 | `job-running-transcript.png` | Monitoring guide, Home page | **Running job transcript tab** — assistant messages, tool call groups (some collapsed, some expanded), progress headline, approval banner if possible |
| D5 | `job-running-logs.png` | Monitoring guide | Structured logs with mixed levels (debug/info/warn/error), level filter dropdown visible |
| D6 | `job-running-timeline.png` | Monitoring guide | Execution timeline with active + completed stages |
| D7 | `job-running-metrics.png` | Monitoring guide | Token usage bars, cost display, LLM calls, tool calls breakdown |
| D8 | `job-running-plan.png` | Monitoring guide | Agent plan with done/active/pending steps |
| D9 | `job-diff-viewer.png` | Code Review guide, Home page | Diff viewer with multi-file changes, file list sidebar, syntax-highlighted diff content |
| D10 | `job-workspace.png` | Code Review guide | Workspace file browser showing directory tree and file content |
| D11 | `approval-banner.png` | Approvals guide | Close-up of approval banner with approve/reject/trust buttons and permission request details (can crop from D4) |
| D12 | `complete-job-dialog.png` | Merging guide | CompleteJobDialog showing all options: merge, smart merge, create PR, discard, agent merge |
| D13 | `terminal-drawer.png` | Terminal guide | Terminal drawer open at bottom with xterm.js session, tab bar showing 2+ sessions |
| D14 | `command-palette.png` | Command Palette guide | Command palette overlay (⌘K) with search input and job results listed |
| D15 | `settings-page.png` | Configuration ref, Getting Started | Settings page showing repo list, SDK selection, preferences |
| D16 | `history-page.png` | History guide | Archived jobs list with search/filter |
| D17 | `voice-recording.png` | Voice Input guide | Voice recording in progress — waveform visible, mic button active/red |
| D18 | `job-succeeded.png` | Monitoring guide | Completed job showing success state badge, final transcript, available actions |
| D19 | `job-failed.png` | Monitoring guide | Failed job showing error state badge, error details in transcript |

## Mobile Screenshots (393×852 — iPhone 14 Pro, 2× retina)

**Directory:** `docs/images/screenshots/mobile/`

Use Chrome DevTools → Device Toolbar → iPhone 14 Pro (393×852) for consistent captures.

| # | Filename | Where Used | What to Capture |
|---|----------|-----------|-----------------|
| M1 | `mobile-dashboard.png` | Home page, Remote Access guide | MobileJobList with tab interface (In Progress / Awaiting / Failed), showing 2-3 job cards |
| M2 | `mobile-dashboard-search.png` | Home page | Mobile dashboard with search bar active and filtered results |
| M3 | `mobile-job-creation.png` | Creating Jobs guide | Job creation form on mobile — compact textarea, dropdowns stacked |
| M4 | `mobile-job-transcript.png` | Monitoring guide | Running job transcript on mobile — messages, tool calls in compact layout |
| M5 | `mobile-job-approval.png` | Approvals guide | Approval banner on mobile with stacked approve/reject buttons |
| M6 | `mobile-job-diff.png` | Code Review guide | Diff viewer on mobile — scrollable, syntax-highlighted |
| M7 | `mobile-terminal.png` | Terminal guide | Terminal drawer maximized (90vh) on mobile |
| M8 | `mobile-settings.png` | Configuration ref | Settings page on mobile |
| M9 | `mobile-voice.png` | Voice Input guide | Voice recording waveform on mobile |
| M10 | `mobile-complete-dialog.png` | Merging guide | Complete/merge dialog on mobile |

## Architecture Diagrams (SVG)

**Directory:** `docs/images/`

| # | Filename | Where Used | Content |
|---|----------|-----------|---------|
| A1 | `architecture-overview.svg` | Architecture index, Home page | Full system diagram: Browser → FastAPI → SQLite / Git / Copilot SDK / Claude SDK / Whisper. Show HTTP/SSE/WebSocket connections |
| A2 | `job-state-machine.svg` | Job States reference | State transition diagram: queued → running → succeeded/failed/canceled, with waiting_for_approval, paused edges |
| A3 | `event-flow.svg` | Architecture backend page | Domain Event → Event Bus → SSE Manager → Browser SSE connection |
| A4 | `approval-flow.svg` | Approvals guide, Architecture | Sequence: Agent action → permission check → approval_requested event → SSE to browser → operator approve/reject → agent continues/stops |

## Capture Tips

1. **Run the app** with realistic data — create 3-4 jobs in different states before capturing
2. **Desktop**: Use a clean browser window at exactly 1280×800 viewport, crop browser chrome
3. **Mobile**: Use Chrome DevTools device toolbar, select iPhone 14 Pro (393×852)
4. **Retina**: Capture at 2× device pixel ratio for crisp rendering
5. **Dark mode**: Optionally capture a second set in dark mode (suffix `-dark.png`)
6. **Consistency**: Use the same repos/prompts across all screenshots for a cohesive story
