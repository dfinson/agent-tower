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

<span class="eyebrow">Run coding agents. Supervise from anywhere.</span>

**No IDE. No terminal. Just a prompt.**

CodePlane runs Claude Code and GitHub Copilot on your workstation — supervise from any browser on your desktop, phone, or tablet. Review diffs, approve risky actions, track costs, and merge when you're ready.

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

## The Core Loop

<div class="workflow-grid" markdown>

<div class="workflow-step" markdown>
<span class="step-index">1</span>
### Launch a task
Pick a repository, write a prompt, choose an agent and model. The agent runs in an isolated Git worktree — your working directory is never touched.
</div>

<div class="workflow-step" markdown>
<span class="step-index">2</span>
### Supervise the run
Watch the transcript, logs, plan progress, and cost data while the agent works. Send messages to steer it if needed.
</div>

<div class="workflow-step" markdown>
<span class="step-index">3</span>
### Gate risky actions
File writes, shell commands, and destructive operations can require your approval before they execute.
</div>

<div class="workflow-step" markdown>
<span class="step-index">4</span>
### Land or discard
Review the diff, then merge, create a PR, or discard — based on what the agent actually produced.
</div>

</div>

## Supported Agents

CodePlane works with **GitHub Copilot CLI** and **Claude Code CLI**. Install and authenticate either CLI, select your agent and model per job — CodePlane manages the underlying SDKs and handles the rest.

External agents can orchestrate CodePlane programmatically through its built-in [MCP server](mcp-server.md) — compatible with VS Code, Claude Desktop, Cursor, and any MCP-compatible client.

## What You Get

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
### :material-play-circle: Task Orchestration
Launch jobs with a prompt and model selection. Each job runs in its own Git worktree for safe, concurrent execution.
</div>

<div class="feature-card" markdown>
### :material-cellphone-link: Mobile-First & Remote
Run on your workstation, control from any browser — phone, tablet, or desktop. UI is touch-optimised. Remote access out of the box via Dev Tunnels or Cloudflare Tunnels.
</div>

<div class="feature-card" markdown>
### :material-monitor-eye: Live Visibility
Transcript, logs, timeline, plan steps, and token costs — all streaming in real time as the agent works.
</div>

<div class="feature-card" markdown>
### :material-shield-check: Approval Gates
Risky operations pause for your review. Approve, reject, or trust the session to auto-approve the rest.
</div>

<div class="feature-card" markdown>
### :material-code-tags: Diff Review & Merge
Syntax-highlighted diffs, workspace browsing, and merge/PR/discard controls — all built in.
</div>

<div class="feature-card" markdown>
### :material-chart-line: Cost Analytics
Track token usage, costs, model performance, and tool health across all jobs.
</div>

</div>

