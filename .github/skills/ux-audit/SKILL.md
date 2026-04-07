---
name: ux-audit
description: "Dogfood the CodePlane web UI — browse as a real user, notice friction, document findings. Adopts a user persona, tracks emotional friction (trust, anxiety, confusion), counts click efficiency, tests resilience, and asks 'would I come back?'. Produces ranked audit reports. Trigger with 'ux audit', 'dogfood this', 'ux walkthrough', 'qa test', or 'check all pages'."
---

# UX Audit

Dogfood the CodePlane web app by walking through it as a real user would — with their goals, their patience, and their context. Goes beyond "does it work?" to "is it good?" by tracking emotional friction (trust, anxiety, confusion), counting click efficiency, testing resilience, and asking: "would I come back?"

Produces structured audit reports with findings ranked by impact.

## Context

CodePlane is a control plane for running and supervising coding agents. It has:
- A React + TypeScript frontend (Vite, Zustand, Tailwind)
- The server runs at `http://localhost:8080`
- Key pages: job list, job detail (with plan steps, transcript, changes/diff viewer, terminal, analytics)

## How to Audit (No Browser Needed)

Since we don't have browser automation, audit by **reading the source code as a user proxy**:

1. **Read the router** to discover all pages and routes
2. **Read each page component** top-to-bottom, mentally rendering what the user sees
3. **Trace user flows** through the component tree — what happens when they click?
4. **Check the store** for state management — what data drives each view?
5. **Read CSS/Tailwind classes** to understand layout, spacing, responsiveness

## Operating Modes

### Mode 1: UX Walkthrough (Dogfooding)

**When**: "ux walkthrough", "walk through the app", "is the app intuitive?", "ux audit", "dogfood this"

#### Step 1: Adopt a User Persona

Ask the user two questions:
- **Task scenario**: What does the user need to accomplish?
- **Who is the user?**: What's their context?

If not specified, adopt: a developer who just kicked off a coding agent and wants to understand what it's doing, whether it's stuck, and what files it changed.

#### Step 2: Approach with Fresh Eyes

Read the entry-point component. From here, attempt the task with **no prior knowledge of the UI**:
- Don't assume labels mean what a developer intended — read them literally
- If something is confusing in the code, that's a finding
- If the user would be uncertain about what a button does, that's a finding

#### Step 3: Evaluate Each Screen

At each screen/component, evaluate:

**Layout**: Is all text fully visible? Nothing clipped or overlapping? Spacing consistent?
**Comprehension**: Do I understand what this page is for and what I can do here? Do the labels make sense?
**Wayfinding**: Do I know where I am? Can I get back? Does the nav show my location?
**Flow**: Does this page connect naturally to the last one? Is the next step obvious?
**Trust**: Do I feel confident this will do what I expect?
**Efficiency**: How many clicks/steps is this taking? Is there a shorter path?
**Recovery**: If I make a mistake, can I get back?

#### Step 4: Count the Cost

Track effort required:
- **Click count**: How many clicks from start to finish?
- **Decision points**: How many times did I have to stop and think?
- **Dead ends**: Wrong paths requiring backtracking?
- **Time impression**: Does this feel fast or tedious?

#### Step 5: Test Resilience

- Navigate away mid-flow — is state preserved?
- What happens with empty states? Error states?
- Does the UI handle loading gracefully?
- What about stale data / reconnection?

#### Step 6: Ask the Big Questions

- **Would I come back?** Or would I look for an alternative?
- **Could I teach a colleague?** In under 2 minutes?
- **What's the one thing that would make this twice as easy?**

#### Step 7: Document findings

Write report to `docs/ux-audit-YYYY-MM-DD.md` with:
- Executive summary
- Findings by severity (Critical > High > Medium > Low)
- Screenshots descriptions / code references
- Recommended fixes

### Mode 2: QA Sweep

**When**: "qa test", "test all pages", "check everything works"

Systematic code-level testing of all pages:

1. **Discover pages**: Read the router config
2. **For each page/feature**:
   - Component renders all expected elements
   - Data flows correctly from store
   - Empty states handled
   - Error states handled
   - Loading states present
   - Dark mode: classes handle both themes
   - Mobile: responsive breakpoints work
3. Produce a QA sweep summary table

### Mode 3: Targeted Check

**When**: "check [feature]", "test [page]", "verify [component]"

Focused code review of a specific area — all states, edge cases, error paths.

## Severity Levels

- **Critical** — blocks the user from completing their task
- **High** — causes confusion or significant friction
- **Medium** — suboptimal but workaround exists
- **Low** — polish and minor improvements

## Autonomy Rules

- **Just do it**: Read code, analyze components, evaluate usability
- **Brief confirmation**: Before writing report files
- **Ask first**: Before making code changes based on findings
