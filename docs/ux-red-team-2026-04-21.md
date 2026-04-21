# UI/UX Macro Red Team Audit — 2026-04-21

Scope: macro-level — screen sizes, flow coherence, layout strategy, navigation, information architecture. Not micro-level (button colors, icon choices, copy).

---

## Executive Summary

CodePlane's frontend demonstrates **strong mobile-first intent** — there is a dedicated mobile job list, a bottom-sheet detail pattern, swipe-based tab navigation, and safe-area handling for notched devices. The desktop layout is well-structured around a resizable sidebar + content pane.

However, the audit surfaces **7 macro-level issues**, several of which compound on each other. The core theme: **the app has two distinct UIs stitched together at the 640px breakpoint, and the seam shows**. Below that breakpoint the experience is thoughtful but constrained; above it the experience is rich but assumes a landscape orientation. The 640–768px gap (portrait tablets, split-screen laptops) gets the worst of both worlds.

---

## FINDING 1: The 640–768px Dead Zone (CRITICAL)

**What**: The entire UI bifurcates at `sm: 640px`. Below it you get mobile (MobileJobList, bottom-sheet, fixed tab bar). Above it you get desktop (KanbanBoard, sidebar, header tabs). There is almost nothing in between.

**Why it matters**: iPad Mini portrait (744px), Samsung Galaxy Tab (800px), and desktop browsers at 2/3 split-screen all land between 640–768px. These users get:
- The full 3-column Kanban grid, which at 640px gives each column ~200px — barely room for a job card
- The desktop header bar instead of the mobile status rail
- No activity sidebar (requires `lg: 1024px`), so the Live tab has no timeline and no swipe gesture to get one — it's simply absent
- The desktop tab bar instead of the mobile bottom nav — but squeezed into a very narrow horizontal strip

**Evidence**:
- `KanbanBoard`: `max-sm:hidden` — visible at 641px+ but `grid-cols-3 max-lg:grid-cols-2` doesn't kick in until 1024px... wait — `max-lg:grid-cols-2` means it's 2-column below 1024px, 3-column above. So at 640–1024px it's a 2-column grid. That's better, but the "Failed" column disappears entirely — it only appears at `lg:`. Users at this breakpoint can't see failed jobs in the Kanban without scrolling or searching.

  **Correction after deeper reading**: The KanbanBoard shows all 3 columns at `grid-cols-3`, and `max-lg:grid-cols-2` drops it to 2. The third column (Failed) likely wraps or gets hidden. This needs verification: does the failed column scroll below the fold, or does it disappear? Either way, users on tablets don't see their failed jobs upfront.

- `ActivityTimeline sidebar`: `hidden lg:flex` — completely absent from 640–1023px. No fallback. On mobile (<640) there's a swipe-to-reveal overlay, but that's also `sm:hidden`. So at 640–1023px, there is **no way to see the activity timeline** at all.

**Recommendation**: 
- Add an `md:` (768px) breakpoint tier. At minimum: show the activity timeline as a collapsible panel or icon toggle at `md:`, not just `lg:`.
- Consider showing a compact 1-column Kanban or card list at `sm:`–`md:` instead of jumping straight to 2-column grid.
- The mobile swipe-to-reveal overlay should also work at `sm:`–`lg:`, not just below `sm:`.

---

## FINDING 2: Activity Timeline Disappears at Tablet Widths (HIGH)

Closely related to Finding 1, but called out separately because it's the most important information architecture issue.

**What**: The activity timeline (plan steps, agent progress) is the primary "where is my agent?" signal. It exists in three forms:
1. Desktop (≥1024px): Persistent sidebar, resizable, always visible
2. Mobile (<640px): Overlay triggered by swipe-right on the Live tab
3. **Tablet (640–1023px): Does not exist in any form**

**Why it matters**: The timeline is the user's mental model of "what's happening." Removing it at tablet widths forces users to read the raw CuratedFeed (a chat-style log) to understand agent progress. This is like removing the table of contents from a book — the content is still there, but navigation is gone.

**Evidence**: 
- Sidebar: `hidden lg:flex`
- Mobile overlay: `sm:hidden absolute inset-0 z-30`
- No `md:` variant exists

**Recommendation**: At `md:` (768px), show the mobile overlay pattern (swipe-to-reveal or a toggle button). The sidebar doesn't need to be persistent at this width, but the overlay should be accessible.

---

## FINDING 3: Job Detail Has No Persistent Location Indicator (HIGH)

**What**: When inside a job detail page, there is no breadcrumb, page title in the header, or other persistent indicator of which job the user is viewing. The header is the same global CodePlane header across all routes.

**On mobile**: The compact status rail shows the job title truncated — this is good. But on desktop (≥640px), the full header shows "CodePlane" logo + search + nav. The job title only appears in the content area, which scrolls.

**Why it matters**: Users working with multiple browser tabs (common for developers monitoring multiple agents) can't tell which job tab they're looking at from the page header alone. They must scroll to the top or read the browser tab title.

**Evidence**:
- `App.tsx` header: Same logo + search + nav on all routes
- `JobDetailScreen`: Job title in the content area, not in the header
- Mobile: Status rail replaces header, shows title — correct behavior

**Recommendation**: On `JobDetailScreen`, inject the job title (truncated) into the header bar. Something like: `CodePlane / Fix authentication bug`. This is a one-line change in the header rendering logic, conditioned on `isJobDetail`.

---

## FINDING 4: Mobile Bottom Tab Bar Has 6+ Tabs (MEDIUM)

**What**: The mobile bottom navigation bar shows: Activity, Live, Shell, Changes, Files, Metrics — and potentially Artifacts (7 items). On a 375px screen, each tab gets ~53px of horizontal space. The icon is 20px and the label is `text-[10px]`.

**Why it matters**: 
- iOS and Android design guidelines recommend a maximum of 5 bottom tab items. Beyond that, use a "More" overflow pattern.
- At 7 items on 375px, each tab is barely 53px wide. Touch targets are fine vertically (`flex-1` with the full height of the nav bar), but the visual density makes it hard to distinguish tabs at a glance.
- The "Activity" tab is a special case — it opens an overlay rather than switching content. This is conceptually different from the other tabs but looks identical in the nav bar.

**Evidence**:
- Bottom nav: `flex items-end justify-around` with `flex-1` children
- Items: Activity (overlay), Live, Shell, Changes, Files, Metrics, [Artifacts]
- No overflow/more pattern

**Recommendation**:
- Merge "Shell" and "Files" into a single "Workspace" tab with a sub-toggle, OR
- Move Metrics and Artifacts behind a "More" tab, OR  
- Make Activity a distinct visual element (left-aligned icon-only toggle rather than a tab-shaped button)

---

## FINDING 5: Diff Viewer Is Unusable Below 768px (MEDIUM)

**What**: The diff viewer stacks vertically on mobile: file list takes 30% of viewport height, Monaco diff editor takes the rest. Monaco switches to inline diff mode (not side-by-side).

**Why it matters**:
- 30% of a 667px viewport (iPhone SE) = 200px for the file list. With padding and borders, that's ~6 files visible. Large PRs with 20+ files require extensive scrolling in a tiny window.
- The Monaco editor at 375px wide with `fontSize: 12` can show roughly 45 characters per line. Most code lines are 80–120 chars, so every line requires horizontal scrolling.
- There is no visible horizontal scroll indicator — users may not realize the diff content extends beyond the viewport.
- Hunk checkboxes (for selective review) are rendered in the glyph margin, which is a narrow touch target in Monaco.

**Evidence**:
- File sidebar: `max-md:max-h-[30%]`
- Monaco: `renderSideBySide: !isMobile`, `fontSize: 12`
- No scroll affordance or hint

**Recommendation**: 
- On mobile, replace the Monaco diff with a simpler HTML-based diff view that can wrap lines and provide larger touch targets for review actions.
- Alternatively, increase the file list to 40% and add a "swipe up to expand" gesture.
- Add a subtle horizontal scroll shadow/gradient indicator on the diff pane.

---

## FINDING 6: Terminal Drawer Height Management Conflicts (MEDIUM)

**What**: The terminal drawer is a persistent bottom panel that overlays the main content area. Its behavior creates layout conflicts:
- Desktop: Resizable from 150px to 70% viewport, default 300px
- Mobile: Capped at 50% viewport
- When the on-screen keyboard opens on mobile, the drawer shifts up by the keyboard height
- The main content area uses `min-h-0` when the terminal is open

**Why it matters**:
- When the terminal is open at 50% on a 667px phone, main content gets ~280px (after header + safe area). That's a very small window to view a diff, feed, or file browser.
- The keyboard offset calculation shifts the drawer upward, but doesn't shrink it — so the drawer can extend above the viewport top if it was already at max height when the keyboard opens.
- The drag handle is `h-7` (28px) — below the 44px touch target minimum for mobile. Users may struggle to resize.

**Evidence**:
- Max height: `window.innerWidth < 640 ? window.innerHeight * 0.5 : window.innerHeight * 0.7`
- Keyboard offset: `translateY(-${keyboardOffset}px)` with no max check
- Drag handle: `h-7 cursor-row-resize`

**Recommendation**:
- On mobile, cap `terminalDrawerHeight + keyboardOffset` to never exceed `window.innerHeight - 100px` (keep 100px of content visible).
- Increase drag handle hit area to 44px on mobile (visual appearance can remain 28px; use invisible padding).
- Consider auto-collapsing the terminal when navigating to a content-heavy tab (diff, files) on mobile.

---

## FINDING 7: No Landscape Orientation Handling on Mobile (LOW)

**What**: The mobile layout uses `100dvh` for heights and `safe-area-inset-bottom` for padding. These are correct for portrait mode. However, there is no specific handling for landscape orientation on phones.

**Why it matters**: 
- In landscape on a phone (e.g., 667px wide × 375px tall on iPhone SE), the viewport height is very short. The `h-[calc(100dvh-92px)]` for the feed becomes ~283px. The bottom tab bar (52px) + header takes significant vertical space, leaving a claustrophobic content area.
- The bottom tab bar in landscape occupies ~14% of vertical space.
- The terminal drawer at 50% max in landscape would leave only ~140px of content.

**Evidence**:
- No `@media (orientation: landscape)` rules or landscape-specific Tailwind classes
- Heights are all `dvh`-based with no landscape compensation
- Bottom nav is always 52px regardless of orientation

**Recommendation**:
- In landscape on small screens, auto-hide the bottom tab bar (show on scroll-up or tap, like mobile browser chrome behavior).
- Reduce terminal drawer max to 40% in landscape.
- Consider a `landscape:` Tailwind plugin or custom utility for the most impacted heights.

---

## Flow Coherence Assessment

### Navigation Graph

```
Dashboard ──→ Job Creation ──→ Job Detail ──→ Dashboard
    │              ↑                │
    │         (Cmd+K / Alt+N)      │
    ├──→ History ←─────────────────┘
    ├──→ Analytics ←───────────────┘
    └──→ Settings
```

**Verdict: GOOD**. Every page has explicit back-navigation. The Command Palette (Cmd+K) acts as a universal escape hatch. No orphan pages. Keyboard shortcuts are consistent and discoverable (shown in nav menu + command palette).

### State Preservation

| Action | State preserved? |
|--------|-----------------|
| Navigate away from job detail, come back | Yes — Zustand store persists |
| Browser refresh on job detail | Yes — fetches from API + SSE reconnects |
| SSE disconnects mid-session | Partial — stale data shown, reconnect auto-retries, status badge updates |
| Job creation form → navigate away → back | No — form state is lost (no draft persistence) |
| Terminal drawer open → switch pages | Yes — terminal persists across routes |

### Error Recovery

| Scenario | Handling |
|----------|----------|
| Route to non-existent job | "Job not found" + back button |
| API failure on job creation | Toast error, form state preserved, can retry |
| Chunk load failure (deploy during session) | Error boundary detects, shows "Reload page" |
| Tab component crash | Tab-level error boundary, other tabs unaffected |
| SSE stream fails | Auto-reconnect with backoff, connection indicator updates |

**Verdict: GOOD**. Error boundaries are layered (global → tab-level). Recovery paths are clear. The chunk-load detection is a particularly nice touch for a production SPA.

### Empty States

| Context | Has empty state? | Quality |
|---------|-----------------|---------|
| Dashboard, no jobs | Yes | Column shows "No {state} jobs" |
| Mobile job list, no jobs | Yes | "No jobs running" |
| History, no archived jobs | Yes | "No archived jobs" with search context |
| Activity timeline, no events | Yes | Icon + "Activity will appear here..." |
| Command palette, no matches | Yes | "No results found" |
| Curated feed, no entries | Partial | Silent — relies on activity timeline empty state |
| Diff viewer, no changes | Yes | "No changes yet" |
| Settings, no repos | Yes | "Add a repository to get started" |

**Verdict: GOOD**, with one gap: the CuratedFeed should have its own empty state message rather than relying on the activity timeline.

---

## Summary — Priority Ranking

| # | Finding | Severity | Impact |
|---|---------|----------|--------|
| 1 | 640–768px dead zone — two UIs stitched at a single breakpoint | **CRITICAL** | Tablet and split-screen users get degraded experience |
| 2 | Activity timeline missing at tablet widths | **HIGH** | Users lose primary progress indicator |
| 3 | No persistent job identifier in header on desktop | **HIGH** | Multi-tab users can't orient |
| 4 | Mobile bottom nav exceeds 5-tab guideline | **MEDIUM** | Visual density, cognitive load |
| 5 | Diff viewer impractical below 768px | **MEDIUM** | Code review workflow broken on mobile |
| 6 | Terminal drawer height conflicts on mobile | **MEDIUM** | Content area crushed when terminal + keyboard open |
| 7 | No landscape handling | **LOW** | Edge case but creates claustrophobic layout |
