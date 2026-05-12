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

A local server that launches agent jobs headless or mirrors the native CLI sessions you already run. You get supervision, cost intelligence, structural review, decision trails, and workspace memory. The agents do the work; CodePlane makes it reviewable.

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
Write a prompt, pick a repo and model. The agent runs headless in an isolated worktree. Review the diff when it's done — approve from your phone or desktop.
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
Launch headless jobs, gate risky actions for approval, supervise from any device. Push notifications for approvals and completions.
</div>

<div class="feature-card" markdown>
### :material-graph: Decision Trail
What the agent did, why it did it, where it backtracked. Full reasoning history — not just a transcript.
</div>

<div class="feature-card" markdown>
### :material-shield-check: Structural Risk Scoring
Breaking vs. additive changes, coupling risks, merge confidence verdict — before you read a single line of diff.
</div>

<div class="feature-card" markdown>
### :material-chart-line: Cost Intelligence
Every turn classified by activity. Waste patterns surfaced across jobs — rework, rereads, cost escalation.
</div>

<div class="feature-card" markdown>
### :material-brain: Workspace Memory
Per-repo knowledge that carries forward. Each new job starts smarter than the last.
</div>

<div class="feature-card" markdown>
### :material-book-open-variant: Narrative Review
Answers "why was this change made?" with verified file references. No hallucinated summaries.
</div>

</div>

## Bring Your Own CLI

CodePlane doesn't contain an AI model. It wraps the agent CLIs you already have installed and authenticated — Claude Code and GitHub Copilot. Install, authenticate, and CodePlane handles the rest.

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

