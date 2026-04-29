---
title: "Transcript Visual Refresh: Presence, Temperature, and Liveness"
description: "Design audit and implementation plan for the CuratedFeed transcript, addressing ghost UI, monochrome temperature, liveness signals, and avatar noise."
author: design-review
ms.date: 2026-04-29
ms.topic: concept
---

## Context

The CuratedFeed transcript is the primary surface of CodePlane. Users spend
most of their session watching this feed. It must communicate agent state, tool
activity, reasoning, and conclusions at a glance.

The current implementation uses opacity values (`/5` to `/15`) that produce
functionally invisible elements against the `hsl(220 20% 7%)` background. The
conversation lacks visual substance, liveness, and temperature contrast between
element types.

### Mental Model

This is an agent supervision feed, not a two-party messenger. User messages
are rare landmarks (roughly 5% of entries). The feed is 95% agent activity.

Visual priority hierarchy:

1. Agent activity state: working, done, or errored
2. Agent conclusions: the high-signal message content
3. Tool context: what it touched, in what order
4. User landmarks: rare directional anchors

Design decisions flow from this hierarchy. Elements that serve monitoring
(liveness, state differentiation) take priority over elements borrowed from
chat-app conventions (per-message avatars, bubble symmetry).

---

## Audit Findings

### F1: Ghost UI

Every content container uses near-zero opacity fills. Against `hsl(220 20% 7%)`
these are invisible.

| Element | Current Value | Effective Result |
|---|---|---|
| Agent bubble idle | `bg-muted/5` | ~0.5% lightness delta from background |
| Agent bubble streaming | `bg-primary/5` | Indistinguishable from idle |
| Phase box expanded | `bg-muted/5 border-border/40` | Container barely visible |
| Tool cluster icons | `text-*-400/50` | Semantic color unreadable |
| Reasoning border | `border-primary/15` | Ghost line |
| Reasoning text | `text-foreground/50` | Below comfortable reading threshold |
| Duration/metadata | `opacity-30` | Invisible unless actively looking |
| Tool group summaries | `text-muted-foreground/40` | Wasted AI-generated context |

The feed reads as text floating in a void rather than structured content within
visible regions.

### F2: No Liveness Signal

Streaming agent turns look identical to completed turns. The only indicator is a
tiny `w-1.5 h-4` blinking cursor inside the message body. A user cannot glance
at the feed and determine whether the agent is actively working.

The CSS already defines `animate-activity-shimmer` (a 3s ambient gradient sweep)
and `animate-reasoning-pulse` (a 4s border-color oscillation). Neither is used
on the primary content area during streaming.

### F3: Agent Avatar Is Noise

A `w-5 h-5` avatar appears on every agent turn. In a feed that is 95% agent
content, this is:

- Redundant: the user already knows the content is from the agent
- Clutter: it repeats 20+ times per session
- Space loss: 28-32px of left gutter consumed per row

The avatar adds value only when multiple SDKs are active (Claude vs Codex vs
custom), where the SDK icon differentiates producers. In single-SDK sessions it
is pure noise.

### F4: Blue Monochrome

The design system layers blue at every level:

| Layer | Value | Saturation |
|---|---|---|
| Background | `hsl(220 20% 7%)` | 20% |
| Card | `hsl(215 22% 11%)` | 22% |
| Primary accent | `hsl(217 91% 60%)` | 91% |
| Muted | `hsl(215 18% 17%)` | 18% |
| Border | `hsl(215 12% 21%)` | 12% |

Background, content containers, accent, operator messages, and streaming state
all share the same blue temperature. Nothing contrasts by warmth. Agent content
and user landmarks melt into the same visual spectrum.

### F5: Operator Messages Underweight

Current `bg-primary/10 border-primary/20` produces a barely-visible fill.
Operator messages are rare (1 in ~20 entries) and serve as timeline anchors for
"here is where I gave direction." They should be distinct without being loud.
Right-alignment already does most of the differentiation; the fill needs to
reinforce it.

### F6: Reasoning Is Buried

The thinking section (`border-l-2 border-primary/15`, `text-foreground/50`) is
so faded it might as well not exist. Reasoning is interesting secondary content
that users should notice and optionally engage with. The "Thinking..." label at
`text-primary/40` is invisible.

### F7: Tool Group Summaries Wasted

AI-generated collapsed summaries at `text-muted-foreground/40` are invisible.
These carry high-value context ("Updated the router to handle auth redirects")
that tells more than "Edited 3 files" at zero extra interaction cost.

### F8: No Entry Presence

The streaming-to-idle transition is silent. New content appears with no arrival
weight. The CSS defines `animate-feed-enter` (250ms fade + 8px slide-up) but it
is underused.

---

## Recommendations

### R1: Raise Content Containers to Visible Thresholds

| Element | Before | After |
|---|---|---|
| Agent bubble idle | `bg-muted/5` | `bg-card/60` |
| Agent bubble streaming | `bg-primary/5` | `bg-card/90 border border-primary/20 animate-activity-shimmer` |
| Phase box expanded | `bg-muted/5 border-border/40` | `bg-muted/10 border-border/50` |
| Phase box collapsed hover | `hover:bg-accent/30 hover:border-border/40` | `hover:bg-accent/40 hover:border-border/50` |
| Condensed reasoning wrap | `bg-muted/5` | `bg-card/40` |

The `card` color (`hsl(215 22% 11%)`) at 60% opacity produces a visible
container with a ~2% lightness bump over the background, which is enough to
define a content region without being heavy.

### R2: Liveness Through Shimmer

Apply `animate-activity-shimmer` to streaming agent bubbles. This is a
directional left-to-right gradient sweep at 3s cadence using `primary` at 6%
opacity. Combined with `border border-primary/20`, it creates an ambient
breathing effect that communicates "working" without distraction.

The shimmer stops when the turn completes and the border drops via normal
re-render (streaming class removed). The transition from alive to settled is
implicit.

### R3: Conditional Agent Avatar

- Remove the avatar column from `AgentTurnBlock`. The content area recovers
  full width. Agent identity is implicit in a single-job feed.
- `SubAgentBubble` retains its own SDK icon for sub-agent differentiation.
- `AgentActivityBar` retains its SDK icon as the persistent "who is working"
  indicator at the bottom of the feed.

### R4: Break the Blue Monochrome

Desaturate the `--card` variable from `hsl(215 22% 11%)` to
`hsl(220 12% 11%)`. This drops saturation from 22% to 12% while keeping
lightness identical.

Effect: agent content containers become near-neutral reading surfaces. Blue
accents (streaming border, operator fill, primary actions) now stand out as
intentional signals rather than blending into same-temperature everything.

The hierarchy becomes:

- Blue-gray shell: background, sidebar, headers (unchanged)
- Neutral content: agent message areas, phase boxes
- Blue signals: streaming state, operator landmarks, interactive elements

> [!NOTE]
> This change touches a single CSS variable and cascades through all `card`
> usages (popovers, dialogs, panels). Verify that card backgrounds in
> non-transcript contexts remain acceptable at the reduced saturation.

### R5: Operator Message Visibility

Raise from `bg-primary/10 border-primary/20` to `bg-primary/18 border-primary/25`.
A moderate bump. The fill becomes perceptible when scanning vertically without
dominating the feed. Combined with right-alignment and the user avatar (which is
appropriate here because operator messages are rare), these serve as clear
timeline landmarks.

> [!NOTE]
> The earlier committed change uses `bg-primary/20 border-primary/30`, which may
> be slightly too prominent given how rare these messages are. Consider backing
> down to `/18` and `/25` after visual testing.

### R6: Reasoning Visibility

| Token | Before | After |
|---|---|---|
| Text | `text-foreground/50` | `text-foreground/60` |
| Border idle | `border-primary/15` | `border-primary/30` |
| Brain icon | `text-primary/40` | `text-primary/50` |
| Label | `text-primary/40` | `text-primary/50` |

The left border should read as a design element, not a rendering artifact. The
text should be readable without competing with the conclusion above it.

### R7: Tool Ecosystem Visibility

| Token | Before | After |
|---|---|---|
| Cluster icons | `text-*-400/50` | `text-*-400/70` |
| File chips unselected | `bg-muted/30` | `bg-muted/40` |
| File chips selected | `bg-primary/15 border-primary/30` | `bg-primary/20 border-primary/40` |
| Duration labels | `opacity-30` | `opacity-40` |
| Chevrons | `opacity-30` | `opacity-40` |
| Tool group summaries | `text-muted-foreground/40` | `text-muted-foreground/55` |

Semantic colors (blue for read, amber for write, emerald for create/execute,
violet for search) become readable. Duration and disclosure affordances become
discoverable.

### R8: Entry Presence

Ensure `animate-feed-enter` fires on newly-appended feed items. The 250ms
fade + 8px slide-up gives arriving content a moment of visual presence before
it settles into the feed. This is especially valuable for agent conclusion
messages: the user sees it "land."

---

## Impact Analysis

### Files Affected

| File | Change Type | Risk |
|---|---|---|
| `frontend/src/index.css` | CSS variable tweak (`--card` saturation) | Low. Single variable, cascades broadly. Requires visual check of all card usages. |
| `frontend/src/components/CuratedFeed.tsx` | Tailwind class changes across ~15 locations | Low. Pure styling, no logic changes. |
| `frontend/src/components/CuratedFeed.tsx` | Conditional avatar rendering (R3) | Medium. Requires SDK detection logic and layout shift when avatar is absent. |

### What Does Not Change

- Store shape, SSE handlers, API contract: untouched
- Backend: untouched
- Transcript data model: untouched
- Markdown rendering (AgentMarkdown): untouched
- ToolRenderers: untouched (their internal styling is separate from container
  styling)
- Mobile layout: responsive prefixes (`sm:`) remain in place

### Risk Areas

| Risk | Mitigation |
|---|---|
| `--card` desaturation affects non-transcript surfaces (dialogs, popovers, sidebar cards) | Audit all `bg-card` usages. The change is from 22% to 12% saturation at identical lightness, so the visual difference is subtle. Revert is a one-line CSS change. |
| Avatar removal shifts layout in single-SDK mode | Content already uses `flex-1 min-w-0` so it fills available space. Test that message text alignment remains clean without the avatar gutter. |
| Shimmer animation on streaming could feel distracting in long sessions | The shimmer uses 6% opacity at 3s cadence, which is below the distraction threshold. Can be disabled with a user preference flag if needed. |
| Raised opacity values on dark mode could reduce the "breathing room" feel | All values stay well below 100%. The lightest container (`bg-card/90` during streaming) resolves to roughly `hsl(220 12% 10.5%)`, still dark. |

### Accessibility Notes

- Contrast ratios improve uniformly. No WCAG regressions.
- `animate-activity-shimmer` uses `background-position` animation, not color
  flashing, so it does not trigger photosensitive seizure concerns. Respects
  `prefers-reduced-motion` if a media query wrapper is added (recommend doing
  so).
- Removing the avatar does not remove semantic information; the content role is
  already conveyed by layout position and entry structure.

---

## Implementation Plan

### Phase 1: Ghost UI Fix (P0)

Raise all content container opacities per R1 and R7. Apply shimmer per R2.
These are pure Tailwind class changes in CuratedFeed.tsx.

Estimated scope: ~15 class string edits in one file.

Status: **done.** Agent bubbles use `bg-card/60` (idle) and
`bg-card/90 border-primary/20 animate-activity-shimmer` (streaming). Phase
boxes raised to `bg-muted/10 border-border/50`. Tool icons at `/70`. Reasoning
at `text-foreground/60 border-primary/30`.

### Phase 2: Temperature Separation (P1)

Modify `--card` in `index.css` from `215 22% 11%` to `220 12% 11%`. Audit all
`bg-card` usages across the frontend for visual acceptability.

Estimated scope: 1 CSS variable change + visual audit.

Status: **done.** Card saturation dropped from 22% to 12%.

### Phase 3: Avatar Simplification (P1)

Remove the avatar column from agent turn blocks. The `AgentActivityBar` and
`SubAgentBubble` retain SDK icons where they add value.

Estimated scope: Remove flex+avatar wrapper from two locations in
CuratedFeed.tsx.

Status: **done.** Agent message containers are now full-width without a
gutter avatar.

### Phase 4: Polish (P2-P3)

- Operator message fine-tuning (R5): adjusted to `bg-primary/[0.18]
  border-primary/25`
- Tool group summary visibility (R7): raised to
  `text-muted-foreground/[0.55]`
- `prefers-reduced-motion` guard: added for `animate-activity-shimmer`,
  `animate-reasoning-pulse`, `animate-feed-enter`, and `animate-glow-flicker`
- Entry presence animation (R8): `animate-feed-enter` applied to all
  newly-appended items via hydration count tracking

Status: **done.**

### Verification

Each phase should be verified by:

1. Running a live job with streaming to confirm liveness feel
2. Scrolling a completed transcript to confirm scan readability
3. Checking multi-SDK sessions for avatar/badge behavior
4. Spot-checking non-transcript card usages (settings panels, dialogs, job
   list) after the `--card` change
5. Running the existing Playwright transcript-timeline spec to confirm no
   regressions

---

## Appendix: Current CSS Variable Reference

```css
--background:  220 20%  7%;    /* near-black, blue-tinted */
--card:        215 22% 11%;    /* content containers — target for desaturation */
--primary:     217 91% 60%;    /* blue accent */
--muted:       215 18% 17%;    /* subtle fills */
--border:      215 12% 21%;    /* borders */
--foreground:  213 27% 90%;    /* text */
```

## Appendix: Existing CSS Animations (Unused or Underused)

| Animation | Definition | Current Usage | Proposed Usage |
|---|---|---|---|
| `animate-activity-shimmer` | 3s directional gradient sweep, primary at 6% | Inline running-tool indicator only | Streaming agent bubbles |
| `animate-feed-enter` | 250ms fade + 8px slide-up | Some feed items | All newly-appended items |
| `animate-reasoning-pulse` | 4s border-color oscillation | Live reasoning border | No change (already correct) |
| `animate-glow-flicker` | 2.5s box-shadow pulse | Navigation scroll-to highlight | No change |
