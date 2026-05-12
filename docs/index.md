---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

<p align="center" markdown>
![CodePlane](images/logo.png){ width="180" }
</p>

# CodePlane

<span class="eyebrow">Orchestration and observability for coding agents. Bring your own CLI.</span>

**Keep using Claude Code or Copilot in your terminal. CodePlane watches, analyzes, and adds the layers they don't have.**

CodePlane is a local server that either launches agent jobs for you (headless, fire-and-forget) or mirrors the native CLI sessions you're already running — same pipeline either way. You get a supervision dashboard, cost intelligence, structural code review, decision trails, and persistent workspace memory. The agents do the work; CodePlane makes the work reviewable.

<div class="hero-actions" markdown>
[Quick Start](quick-start.md){ .md-button .md-button--primary }
[Usage Guide](guide.md){ .md-button }
[How It Works](architecture.md){ .md-button }
</div>

<p class="works-with">Works with <strong>Claude Code CLI</strong> and <strong>GitHub Copilot CLI</strong> &nbsp;·&nbsp; Open source, MIT license</p>

</div>

<div class="screenshot-desktop" markdown>
![CodePlane Dashboard](images/screenshots/desktop/hero-dashboard.png)
</div>

<div class="screenshot-mobile" markdown>
![CodePlane Dashboard — Mobile](images/screenshots/mobile/hero-dashboard.png)
</div>

## Two Modes, One Pipeline

<div class="workflow-grid" markdown>

<div class="workflow-step" markdown>
<span class="step-index">A</span>
### Launch through CodePlane
Write a prompt, pick a repo and model. The agent runs headless in an isolated worktree. Close your laptop — approve and review from your phone later.
</div>

<div class="workflow-step" markdown>
<span class="step-index">B</span>
### Mirror your native sessions
Run `claude` or `copilot` in your terminal as usual. CodePlane auto-discovers the session via file-tailing and ingests it — full dashboard, cost tracking, and trail enrichment with zero workflow change.
</div>

</div>

Either way, you get the same intelligence: trail enrichment, cost attribution, structural review, and workspace memory.

## What You Get

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
### :material-play-circle: Orchestration & Supervision
Launch headless jobs, gate risky actions for approval, supervise from any browser (phone, tablet, desktop). Push notifications for approvals, completions, and failures.
</div>

<div class="feature-card" markdown>
### :material-graph: Semantic Trail
Every agent decision is recorded and enriched — intent classification, backtrack detection, insight extraction. See not just what the agent did, but how it reasoned its way there.
</div>

<div class="feature-card" markdown>
### :material-shield-check: Structural Code Review
Tree-sitter diffs classify changes as breaking, body, additive, or non-structural. Community detection surfaces coupling risks. Merge confidence verdict (HIGH/MEDIUM/LOW) before you read a single line.
</div>

<div class="feature-card" markdown>
### :material-chart-line: Cost Intelligence
Every turn classified by activity (implementation, debugging, investigation, overhead). Cross-job waste detection: file reread hotspots, retry waste, cost escalation, cache regression.
</div>

<div class="feature-card" markdown>
### :material-brain: Workspace Memory
Persistent per-repo knowledge — decisions, wisdom, lessons — curated and injected into each new job by relevance. Job N+1 starts smarter than job N.
</div>

<div class="feature-card" markdown>
### :material-book-open-variant: Narrative Review
Structured code-review stories with verified file references (never hallucinated) and LLM-generated prose. Answers "why was this change made?" at file and edit level.
</div>

</div>

## Bring Your Own CLI

CodePlane doesn't contain an AI model. It wraps the agent CLIs you already have installed and authenticated:

- **Claude Code CLI** — sessions discovered via `~/.claude/projects/` JSONL files
- **GitHub Copilot CLI** — sessions discovered via `~/.copilot/session-store.db`

Install either CLI, authenticate it, and CodePlane handles the rest — whether you launch through the UI or just use your terminal.

## Supported Agents

| Agent | Managed (headless) | Mirrored (native CLI) |
|-------|-------------------|-----------------------|
| Claude Code | Yes | Yes |
| GitHub Copilot | Yes | Yes |

External agents can also orchestrate CodePlane programmatically through its built-in [MCP server](mcp-server.md).

## The Core Loop

<div class="workflow-grid" markdown>

<div class="workflow-step" markdown>
<span class="step-index">1</span>
### Launch or discover
Create a job from the UI, or just start a native CLI session in a registered repo. Either way it appears on your dashboard.
</div>

<div class="workflow-step" markdown>
<span class="step-index">2</span>
### Supervise
Watch the transcript, plan progress, and live cost while the agent works. Send messages to steer if needed.
</div>

<div class="workflow-step" markdown>
<span class="step-index">3</span>
### Gate risky actions
File writes, shell commands, and destructive operations can require your approval before they execute.
</div>

<div class="workflow-step" markdown>
<span class="step-index">4</span>
### Review with intelligence
Structural risk scoring, narrative review, and motivation provenance — not just a diff.
</div>

<div class="workflow-step" markdown>
<span class="step-index">5</span>
### Land or discard
Merge, create a PR, or discard — based on what the agent produced and what the review tells you.
</div>

</div>

