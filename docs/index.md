---
hide:
  - navigation
  - toc
---

# CodePlane

<div class="hero" markdown>

<span class="eyebrow">Operator-first agent control plane</span>

**Control plane for running and supervising coding agents**

Launch coding tasks against real repositories, watch execution unfold live, and step in before risky actions turn into messy clean-up.

CodePlane is built for the moment after the prompt is sent: approvals, diffs, metrics, recovery, and operator control.

<div class="hero-metrics" markdown>

<div class="hero-metric" markdown>
**Real repositories**

<span>Agents run against actual local codebases, not toy sandboxes.</span>
</div>

<div class="hero-metric" markdown>
**Approval gates**

<span>Risky actions can stop for operator review before they execute.</span>
</div>

<div class="hero-metric" markdown>
**Live telemetry**

<span>Transcript, logs, plan progress, and cost data stay visible during the run.</span>
</div>

<div class="hero-metric" markdown>
**Controlled landing**

<span>Merge, PR, or discard based on the diff instead of trusting the final summary.</span>
</div>

</div>

<div class="hero-actions" markdown>
[Get Started](getting-started/index.md){ .md-button .md-button--primary }
[User Guide](guide/index.md){ .md-button }
[Architecture](architecture/index.md){ .md-button }
</div>

</div>

<div class="screenshot-desktop" markdown>
![CodePlane Dashboard](images/screenshots/desktop/hero-dashboard.png)
</div>

## Why CodePlane?

CodePlane gives you **visibility and control** over autonomous coding agents. Instead of fire-and-forget, you get a real-time control plane where you can monitor execution, review changes, approve risky actions, and intervene at any point.

<p class="section-lead">It is for cases where agent output matters enough that you need to supervise the run, not just inspect the aftermath.</p>

## When It Fits

<div class="decision-grid" markdown>

<div class="decision-card decision-card--good" markdown>
### Use CodePlane when

- the agent is touching a real repository with real branch state
- you want a human in the loop for risky operations
- you care about transcript, cost, and verification visibility
- the outcome needs reviewable provenance, not just a pasted patch
</div>

<div class="decision-card decision-card--bad" markdown>
### Do not start here when

- you just want a fast one-off code answer in chat
- there is no repository or branch workflow to supervise
- the task is so small that approval, review, and merge steps would dominate
- you do not intend to inspect or act on what the agent does
</div>

</div>

<div class="workflow-grid" markdown>

<div class="workflow-step" markdown>
<span class="step-index">1</span>
### Launch scoped work
Choose a repository, model, and prompt for a task that should run in an isolated worktree instead of your live branch.
</div>

<div class="workflow-step" markdown>
<span class="step-index">2</span>
### Supervise the run
Track transcript updates, logs, plan progress, and execution state while the agent explores, edits, and verifies.
</div>

<div class="workflow-step" markdown>
<span class="step-index">3</span>
### Gate risky actions
Approve or reject operations that should not run silently, including destructive shell commands and merge-adjacent behavior.
</div>

<div class="workflow-step" markdown>
<span class="step-index">4</span>
### Decide how changes land
Review the diff, inspect the workspace, and choose merge, PR, or discard based on what the agent actually produced.
</div>

</div>

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
### :material-play-circle: Job Orchestration
Launch coding tasks with a prompt, choose your AI model and SDK, and let the agent work against a real repository in an isolated Git worktree.
</div>

<div class="feature-card" markdown>
### :material-monitor-eye: Live Monitoring
Watch the agent's reasoning, tool calls, logs, and code changes in real time through a rich transcript view with progress tracking.
</div>

<div class="feature-card" markdown>
### :material-shield-check: Approval Gating
Risky operations — file writes, shell commands, network access — can be gated behind operator approval before they execute.
</div>

<div class="feature-card" markdown>
### :material-code-tags: Code Review
Syntax-highlighted diff viewer shows every change the agent makes. Browse the full workspace file tree at any point during execution.
</div>

<div class="feature-card" markdown>
### :material-cellphone-link: Remote Access
Access the UI from your phone or another device via Dev Tunnels. Monitor and control jobs from anywhere over HTTPS.
</div>

<div class="feature-card" markdown>
### :material-microphone: Voice Input
Speak your prompts and instructions directly into the browser. Local Whisper transcription keeps your data private — nothing leaves your machine.
</div>

<div class="feature-card" markdown>
### :material-source-merge: Merge & PR
When a job completes, merge changes directly, use smart merge, or create a pull request — all from the UI.
</div>

<div class="feature-card" markdown>
### :material-console: Terminal Sessions
Integrated terminal with multi-tab support lets you run commands alongside the agent, inspect the workspace, or debug issues.
</div>

</div>

<div class="screenshot-desktop" markdown>
![Live Transcript](images/screenshots/desktop/job-running-transcript.png)
</div>

## What You Actually Control

<p class="section-lead">The product earns its keep if it changes operator behavior during the run, not if it simply gives you a prettier postmortem.</p>

<div class="proof-grid" markdown>

<div class="proof-card" markdown>
### Risky actions
File writes, shell commands, network access, and merge-adjacent operations can be surfaced for operator approval instead of being silently executed.
</div>

<div class="proof-card" markdown>
### Execution quality
Transcript, logs, plan progress, and telemetry make it obvious whether the agent is making progress or thrashing.
</div>

<div class="proof-card" markdown>
### Change management
Review diffs in-flight, inspect the workspace, and choose whether to merge, create a PR, or discard the run.
</div>

</div>

## What Operators Watch First

<div class="section-stack" markdown>

### 1. Is the agent moving forward?
Use the transcript, plan, and timeline together. If the same files, commands, or explanations keep repeating, the run is probably spinning.

### 2. Is the blast radius changing?
Approval requests, shell commands, and merge-adjacent actions are the inflection points where supervision matters most.

### 3. Is the output worth landing?
The decision is made in the diff and workspace view, not in the final success message.

</div>

## Multi-SDK Support

CodePlane works with multiple AI coding agent SDKs:

- **GitHub Copilot** — Use any model available through the Copilot platform
- **Claude Code** — Direct integration with Anthropic's Claude SDK

The agent adapter pattern means adding new SDKs is straightforward — each SDK is wrapped behind a common interface.

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────┐
│                    Operator Browser                      │
│              React + TypeScript Frontend                 │
│          REST (commands/queries) + SSE (live)            │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE / WebSocket
┌────────────────────────▼─────────────────────────────────┐
│               FastAPI Backend (Python)                   │
│  REST API · SSE · Job orchestration · MCP server         │
│  Git service · Agent adapters · Approvals · Terminal     │
│  Voice transcription · Telemetry · Merge service         │
└────┬──────────┬──────────┬──────────┬──────────┬─────────┘
     │          │          │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼─────┐ ┌─▼──────┐ ┌─▼───────┐
│ SQLite │ │  Git   │ │Copilot  │ │ Claude │ │ Whisper │
│   DB   │ │  repos │ │  SDK    │ │  SDK   │ │ (local) │
└────────┘ └────────┘ └─────────┘ └────────┘ └─────────┘
```

<div class="screenshot-desktop" markdown>
![Analytics Dashboard](images/screenshots/desktop/analytics-dashboard.png)
</div>

<div class="screenshot-desktop" markdown>
![Diff Viewer](images/screenshots/desktop/job-diff-viewer.png)
</div>

<div class="screenshot-mobile" markdown>
![Mobile Dashboard](images/screenshots/mobile/mobile-dashboard.png)
</div>
