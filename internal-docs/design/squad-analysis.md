---
title: "Squad Analysis: Multi-Agent Patterns for CodePlane"
description: "What we can learn from bradygaster/squad to empower CodePlane users with multi-agent workflows."
status: research
source: "https://github.com/bradygaster/squad"
---

## Executive Summary

[Squad](https://github.com/bradygaster/squad) (2.5k stars, alpha) provides
human-directed AI agent **teams** through GitHub Copilot. Users describe what
they're building; Squad scaffolds specialist agents (frontend, backend, tester,
lead) that persist as repo files, share decisions, accumulate knowledge, and
work in parallel under human oversight.

CodePlane already has the primitives Squad lacks — a real backend, structured
job lifecycle, cost tracking, an approval system, and an MCP orchestration
server. What CodePlane lacks is the **coordination layer** that turns
independent jobs into collaborative workflows. This document identifies the
Squad concepts worth adopting, ranked by value and alignment with existing
architecture.

---

## What Squad Does That We Don't

| Squad Concept | What It Means | CodePlane Status |
|---|---|---|
| **Coordinator** | Central routing engine that decomposes tasks, assigns to agents by pattern/capability, launches them in parallel | No routing or decomposition — single job, single agent |
| **Agent roles + charters** | Each agent has a persistent identity (role, model, tools, capabilities) stored as repo files | Jobs have no role concept; every job uses the same agent configuration |
| **Parallel execution** | Multiple agents work simultaneously on independent sub-tasks from one user request | Jobs run independently; no shared-goal grouping |
| **Shared decision log** | `decisions.md` records every decision any agent made, visible to all agents and humans | Per-job transcripts exist but don't cross-pollinate |
| **Skills system** | Reusable knowledge distilled from real work, with confidence lifecycle (low → medium → high) | No accumulated knowledge across jobs |
| **Watch mode (Ralph)** | Automated polling loop: triage issues → dispatch agents → monitor → escalate | No automated work intake |
| **Hook pipeline** | Pre/post tool interception with allow/block/modify actions for governance | Action policy is designed but uses a different pattern |
| **Cost-aware routing** | Budget tracking that influences model and tier selection at routing time | Cost tracking exists; tier promotion is designed but not implemented |
| **Response tiers** | direct / lightweight / standard / full — controls how many agents and what model quality | No concept of variable orchestration depth |
| **Ceremonies** | Scheduled team rituals (standups, retros) with agenda and participants | No scheduled or recurring jobs |
| **Upstream inheritance** | Share skills, decisions, and routing rules across teams/repos | No cross-repo knowledge sharing |
| **Plugin marketplace** | Reusable extension packages (skills + ceremonies + directives) | No extension system |

---

## High-Value Opportunities (Build These)

### 1. Job Groups — Coordinated Multi-Job Workflows

**Squad pattern**: The Coordinator decomposes a task, spawns agents in parallel,
and aggregates results.

**CodePlane adaptation**: The MCP orchestration server already lets an outer
agent create multiple jobs. What's missing is a **first-class Job Group**:

- A group has a shared goal description, a set of member jobs, and a
  dependency graph (which jobs can run in parallel, which must sequence).
- The UI shows a group view: aggregate progress, per-job status cards,
  combined diff, shared approval queue.
- The MCP server exposes `codeplane_job` actions: `create_group`, `add_to_group`,
  `get_group`.
- A group can have a **coordinator prompt** that the outer agent uses to decide
  decomposition strategy.

**Why it matters**: This is the single biggest gap between "run one agent on one
task" and "orchestrate a team of agents on a project." It builds on
`parent_job_id` (already in the DB) and the MCP server (already spec'd).

**Effort**: Medium. DB schema changes (job_groups table, group_id FK on jobs),
new service methods, new UI components for group view, MCP tool extensions.

---

### 2. Agent Profiles — Roles with Persistent Configuration

**Squad pattern**: `defineAgent({ name, role, model, tools, capabilities })`.
Each agent has a charter and history.

**CodePlane adaptation**: Let operators define **agent profiles** per repository
or globally:

```
Profile: "backend-engineer"
  model: claude-sonnet-4
  system_prompt_suffix: "You specialize in Python/FastAPI backends..."
  permission_mode: full_auto
  tools_restricted_to: [file_ops, terminal, git]
```

When creating a job (or a job within a group), the operator selects a profile.
The profile configures model, prompt augmentation, permission preset, and tool
restrictions.

**Why it matters**: Specialization improves output quality and lets operators
give different trust levels to different roles (tester gets full_auto; the
database-migration agent gets review_and_approve).

**Effort**: Low-medium. A profiles table, profile selection on job creation,
prompt injection at agent start.

---

### 3. Earned Knowledge / Skills System

**Squad pattern**: Agents write `SKILL.md` files after work. Skills have
confidence levels that increase with successful reuse. All agents can read all
skills.

**CodePlane adaptation**: After a job completes successfully, CodePlane extracts
key decisions and patterns into a **knowledge base** scoped to the repository:

- Structured entries: pattern name, context, steps, source job ID.
- Confidence: starts low, promoted when referenced by subsequent successful
  jobs.
- Injected into future job prompts as context (filterable by relevance).
- Viewable in the UI under repository settings.

**Why it matters**: Knowledge compounding is Squad's killer feature. Without it,
every CodePlane job starts from scratch. With it, the tenth job on a repo is
dramatically better than the first.

**Effort**: Medium. New DB tables (knowledge_entries), extraction logic
(post-job hook or operator-triggered), prompt injection, UI for browsing/editing.

---

### 4. Watch Mode — Automated Work Intake

**Squad pattern**: Ralph polls for GitHub issues, builds context, dispatches
agents, monitors execution, escalates on failure. 4-tier error recovery.

**CodePlane adaptation**: A **watch service** that:

1. Connects to a GitHub repo (or GitLab, ADO) via API.
2. Polls for issues matching configurable filters (labels, assignees, age).
3. For each qualifying issue, auto-creates a CodePlane job with the issue
   as the prompt (or a templated prompt incorporating issue body).
4. Links the resulting PR back to the issue.
5. Escalates failures to the operator via the notification inbox.

The approval system naturally gates risky actions. The operator stays in
control — watch mode feeds the queue, humans approve gates.

**Why it matters**: This is the difference between "I manually create jobs" and
"CodePlane is always working on my backlog." It's the autonomy dial turned up.

**Effort**: Medium-high. New service (WatchService), GitHub API integration,
polling loop, issue-to-job template system, configuration UI.

---

### 5. Cost-Aware Model Routing

**Squad pattern**: `CostTracker` monitors spend; router falls back to cheaper
model tiers when budget thresholds are hit.

**CodePlane adaptation**: The action policy doc already designs cost-rule
promotion (gate when spend exceeds threshold). Extend this to **model
fallback**:

- Define model chains per profile or globally:
  `premium: [claude-opus-4, claude-sonnet-4]`,
  `standard: [claude-sonnet-4, claude-haiku-4]`.
- When a job's cumulative spend crosses a configured threshold, demote to a
  cheaper model for the remainder (or gate for operator approval to continue
  at the current tier).
- Surface spend-vs-budget in the job detail UI and group aggregate view.

**Why it matters**: Cost control is a real concern for users running many jobs.
This makes CodePlane budget-aware without requiring manual intervention.

**Effort**: Low-medium. Builds on existing cost tracking and the action policy
cost rules.

---

## Medium-Value Opportunities (Consider These)

### 6. Shared Decision Log Across Jobs

A structured, append-only log per repository (or job group) recording key
decisions: architectural choices, library selections, convention agreements.
Future jobs receive relevant decisions as context. Different from skills (which
are patterns); decisions are specific choices with rationale.

### 7. Scheduled / Recurring Jobs (Ceremonies)

Cron-like scheduling: nightly test suite runs, weekly dependency update PRs,
daily linting passes. Configuration: prompt template, schedule expression,
repository, profile. Natural extension of watch mode.

### 8. Hook Pipeline for Action Policy

The action policy doc uses a classifier → tier → gate model. Squad's hook
pipeline pattern (ordered chain of pre/post interceptors returning
allow/block/modify) is a cleaner implementation shape. Each policy dimension
(path rules, cost rules, trust grants, tool annotations) becomes a hook in
the pipeline, composable and testable independently.

### 9. Job Templates

Pre-configured prompts + profile + settings for common workflows:
"Fix bug from issue", "Implement feature from spec", "Add test coverage for
module", "Update dependencies". Selectable from the new-job UI. Shareable
across repos.

---

## Lower Priority but Interesting

### 10. Cross-Repo Knowledge Sharing (Upstream Inheritance)

Squad's upstream inheritance lets teams share skills and routing. CodePlane
equivalent: export/import knowledge bases between repos. Useful for
organizations running many repos with shared conventions.

### 11. Plugin/Extension System

A way for users to package and share templates, profiles, knowledge entries,
and watch-mode filters. Low priority until the core features stabilize.

### 12. Agent Casting / Themed Identities

Squad assigns agents names from fictional universes (The Wire, Breaking Bad)
for personality and memorability. Fun but cosmetic — consider as a UX polish
item if agent profiles ship.

---

## What NOT to Adopt

| Squad Pattern | Why Skip It |
|---|---|
| **Markdown-file-based state** (`.squad/` directory) | CodePlane uses a real database with proper schemas, migrations, and ACID transactions. Don't regress. |
| **Interactive CLI shell** | CodePlane's value is the web UI and MCP server. A CLI shell adds surface area with no leverage. |
| **Git-notes / orphan-branch state backends** | Clever for a CLI tool; unnecessary when you have SQLite and a proper persistence layer. |
| **SDK-first TypeScript config** | CodePlane's config is Python/Pydantic. Don't add a parallel TypeScript config surface. |
| **Casting engine complexity** | Multi-universe name registries, overflow strategies — too much ceremony for the value. |
| **Plugin marketplace** | Premature. Ship the core features first. |

---

## Recommended Build Order

```
Phase 1 — Foundation
  ├── Agent Profiles (#2)              ← Enables everything else
  └── Job Groups (#1)                  ← Core multi-agent primitive

Phase 2 — Intelligence
  ├── Earned Knowledge (#3)            ← Knowledge compounding
  └── Shared Decision Log (#6)         ← Cross-job context

Phase 3 — Automation
  ├── Watch Mode (#4)                  ← Automated intake
  ├── Scheduled Jobs (#7)              ← Recurring work
  └── Cost-Aware Routing (#5)          ← Budget guardrails

Phase 4 — Polish
  ├── Job Templates (#9)               ← Faster job creation
  ├── Hook Pipeline (#8)               ← Clean action policy impl
  └── Cross-Repo Knowledge (#10)       ← Org-wide learning
```

---

## Architectural Fit Summary

Squad is a **file-based CLI tool** that leans on GitHub Copilot as the runtime.
CodePlane is a **server-based control plane** with its own runtime, persistence,
and UI. The concepts transfer; the implementation patterns don't.

The key insight from Squad: **the value isn't in running one agent well — it's
in coordinating many agents under human oversight.** CodePlane already has the
oversight primitives (approval system, action policy, MCP server, event bus).
What it needs is the coordination layer on top: grouping, routing, knowledge
accumulation, and automated intake. These build on existing infrastructure
rather than requiring a rewrite.
