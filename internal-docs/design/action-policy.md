---
title: Action Policy
description: "Design for CodePlane's action classification and operator approval system. Binary property classification, DB-persisted rules, trust grants, and a unified notification inbox."
status: proposed
---

## Overview

Action Policy governs when the agent can proceed autonomously and when it must
pause for operator approval. Every action is classified by two observable
properties (reversible, contained), mapped to a tier (observe, checkpoint, gate),
and routed accordingly. The operator configures policy through presets, explicit
rules, and trust grants, all persisted in the database and managed through a
structured settings UI.

## Classification Model

Every action the agent performs is classified by two boolean properties:

| Property | Question |
|----------|----------|
| reversible | Can this be undone without data loss? |
| contained | Does this stay within the local worktree/sandbox? |

These two booleans produce three tiers:

| Tier | Meaning | UX |
|------|---------|-----|
| observe | Logged, no interruption | Streams in timeline |
| checkpoint | Git savepoint taken, then proceeds | Brief flash in timeline |
| gate | Agent stops, operator must approve | Notification in inbox |

### Tier Resolution

```python
def classify(reversible: bool, contained: bool, preset: Preset, policy: RepoPolicy) -> Tier:
    # 1. Explicit rules override everything
    rule = policy.match(action)
    if rule:
        return rule.tier

    # 2. Preset logic
    match preset:
        case Preset.autonomous:
            if not contained:
                return Tier.gate
            return Tier.observe
        case Preset.supervised:
            if not contained or not reversible:
                return Tier.gate
            if not reversible:
                return Tier.checkpoint
            return Tier.observe
        case Preset.strict:
            if reversible and contained:
                return Tier.checkpoint
            return Tier.gate

    # 3. Cost rule promotion — can only promote tier upward
    for rule in policy.cost_rules:
        if cost_condition_met(rule, current_job_spend_usd):
            tier = max(tier, Tier(rule.promote_to))
```

### Cost Rule Evaluation

Cost rules promote tiers **after** preset resolution. They cannot lower a tier.
Each cost rule has a `condition` (human label), `promote_to` (checkpoint or
gate), and an optional `threshold_value` (USD). Evaluation compares the
job's current total spend against the threshold:

```python
def cost_condition_met(rule: dict, job_spend_usd: float) -> bool:
    threshold = rule.get("threshold_value")
    if threshold is None:
        return False  # No threshold configured — rule is informational only
    return job_spend_usd >= threshold
```

The job spend is passed into the classifier as an optional `CostContext`
from the telemetry summary. If no cost data is available (fresh job, no
spans yet), cost rules are skipped.

## Input Channels

Four channels feed into the classifier. Each determines the `reversible` and
`contained` values differently.

### File Operations

Classified algorithmically from the git index:

| Signal | reversible | contained |
|--------|-----------|-----------|
| Tracked file, additive change | True | True |
| Tracked file, destructive (delete/overwrite) | True (git revert) | True |
| File outside worktree | depends | False |
| Binary file overwrite (no meaningful diff) | False | True |

Path rules can override: the operator can escalate `migrations/*.sql` to gate
regardless of properties.

### SDK Tools

The SDK exposes approximately ten tools. Each is statically classified in a
lookup table:

```python
SDK_TOOLS: dict[str, tuple[bool, bool]] = {
    # tool_name: (reversible, contained)
    "create_file":     (True,  True),
    "edit_file":       (True,  True),
    "delete_file":     (True,  True),
    "run_terminal":    (False, True),
    "browser_action":  (False, False),
    "ask_user":        (True,  True),
}
```

`run_terminal` delegates to the shell classifier for finer-grained resolution.

### MCP Tools

Opaque by definition. Classification happens at server declaration time through
two operator-facing questions:

* Can actions be undone? (reversible)
* Stays within local environment? (contained)

Both default to unchecked (conservative: irreversible + uncontained = gate under
supervised/strict).

Tool annotations from the MCP protocol act as a convenience layer. If a tool
declares `readOnlyHint: true`, it gets observe. But the server-level declaration
is the floor. Annotations can only relax within the bounds the operator set.

Per-tool overrides are available after initial setup:

```json
{"tool_overrides": {"get_issue": {"reversible": true, "contained": true}}}
```

### Shell Commands

Cross-platform classifier covering POSIX, PowerShell, and cmd.exe.

#### POSIX

Binary frozensets:

```python
_POSIX_OBSERVE = frozenset({"ls", "cat", "head", "tail", "grep", "find", "wc",
    "echo", "pwd", "env", "printenv", "whoami", "date", "file", "stat"})

_POSIX_UNCONTAINED = frozenset({"curl", "wget", "ssh", "scp", "rsync", "nc",
    "ncat", "telnet", "ftp", "sftp", "sendmail", "mail"})

_POSIX_IRREVERSIBLE = frozenset({"rm", "shred", "dd", "mkfs", "fdisk",
    "kill", "killall", "pkill", "shutdown", "reboot", "halt"})
```

#### PowerShell

Verb prefix taxonomy from Microsoft's approved verb list:

```python
_PS_OBSERVE_VERBS = frozenset({"Get", "Find", "Search", "Test", "Measure",
    "Compare", "Select", "Format", "Out", "Show", "Read", "Watch"})

_PS_MUTATING_VERBS = frozenset({"Set", "New", "Add", "Remove", "Clear",
    "Move", "Rename", "Copy", "Update", "Reset", "Enable", "Disable"})

_PS_UNCONTAINED_VERBS = frozenset({"Send", "Connect", "Disconnect",
    "Publish", "Push", "Invoke-Web"})
```

#### cmd.exe

Builtin sets:

```python
_CMD_OBSERVE = frozenset({"dir", "type", "echo", "set", "ver", "where",
    "findstr", "find", "more", "tree", "path", "vol"})

_CMD_IRREVERSIBLE = frozenset({"del", "erase", "rmdir", "rd", "format"})
```

#### Cross-Platform Tools

Tools like git, npm, cargo, and docker use subcommand classifiers that apply
regardless of shell:

```python
_GIT_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "status": (True, True),   "log": (True, True),    "diff": (True, True),
    "add":    (True, True),   "commit": (True, True), "branch": (True, True),
    "push":   (True, False),  "force-push": (False, False),
    "reset --hard": (False, True),
}

_NPM_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install": (True, True),  "test": (True, True),   "run": (True, True),
    "publish": (False, False),
}
```

The parser extracts binary + first subcommand, looks up in order:
cross-platform table, then platform-specific set. Unknown commands default to
`(False, True)` (irreversible, contained).

## Presets

Three named starting points. Rules can override in either direction: a rule can
relax a gate to observe or escalate an observe to gate.

| Preset | Philosophy | Gates when |
|--------|-----------|-----------|
| autonomous | Maximize flow, interrupt only for external actions | not contained |
| supervised | Balance: interrupt for risky or external | not contained OR not reversible |
| strict | Interrupt by default, approve almost everything | not (reversible AND contained) |

## Trust Grants

Scoped, time-limited permissions that bypass the gate tier for matching actions:

```python
@dataclass
class TrustGrant:
    id: str
    kinds: set[str]              # {"write", "shell", "mcp", "url"}
    path_pattern: str | None     # glob, e.g. "src/**/*.py"
    excludes: list[str]          # globs to exclude from the grant
    command_pattern: str | None  # regex for shell commands
    mcp_server: str | None       # specific MCP server name
    expires_at: datetime | None
    created_at: datetime
    reason: str                  # why this trust was granted
```

Trust grants are created through:

* Inline approval: operator approves a gate action and checks "trust similar actions"
* Settings UI: operator creates grants proactively
* Batch approval: "approve all" on a batch creates a grant covering the pattern

Trust does not create a new tier. It makes gate-tier actions proceed without
interruption for the grant's duration and scope.

## Checkpoint Service

Before any checkpoint-tier or gate-tier action executes, a git savepoint is
created:

```python
class CheckpointService:
    def create(self, job_id: str, action_summary: str) -> str:
        """Create lightweight git tag as savepoint. Returns tag name."""
        tag = f"cp/{job_id}/{self._next_seq()}"
        self._git.tag(tag, message=action_summary)
        return tag

    def rollback(self, checkpoint_ref: str) -> None:
        """Revert all commits since checkpoint. Preserves history."""
        self._git.revert_to_tag(checkpoint_ref)
```

Rollback creates a revert commit (history-preserving). It does not reset.

## Approval Batcher

Gate-tier actions arriving in quick succession are batched into a single
notification:

```python
class ApprovalBatcher:
    """Accumulates gate actions within a time window, emits one batch event."""

    def submit(self, action: GateAction) -> None:
        batch = self._get_or_create_batch(action.job_id)
        batch.actions.append(action)
        batch.reset_timer()

    def _on_window_close(self, batch: Batch) -> None:
        self._event_bus.publish(BatchReady(
            batch_id=batch.id,
            job_id=batch.job_id,
            actions=batch.actions,
            summary=self._summarize(batch.actions),
        ))
```

Window duration is configurable via `policy_config.batch_window_seconds`.

The operator can:

* Approve all: proceeds, optionally creates trust grant
* Approve some: cherry-pick which actions proceed
* Reject all: agent is told to find another approach
* Rollback: revert to pre-batch checkpoint

## Notification Inbox

Unified surface for all job lifecycle events requiring operator attention.

```text
┌─────────────────────────────────────────────────────────────────┐
│  🔔 3                                                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Needs Action                                                   │
│                                                                 │
│  ● job-7: 4 actions need approval           [Review]  2m ago   │
│  ● job-12: merge conflict on main           [Resolve] 5m ago   │
│  ● job-3: budget limit reached              [Decide]  8m ago   │
│                                                                 │
│  Updates                                                        │
│                                                                 │
│  ○ job-7: checkpoint created (migrations)            12m ago   │
│  ○ job-5: completed successfully                     15m ago   │
│  ○ job-9: failed, test suite red                     20m ago   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

* Badge count reflects "Needs Action" items only.
* Clicking "Review" on a batch opens the batch detail with diffs and
  approve/reject controls.
* "Updates" is informational with no action required.
* Items auto-dismiss from "Needs Action" when resolved.

## Persistence

All policy configuration lives in SQLite alongside jobs and audit data. No config
file in the worktree.

### Schema

```sql
CREATE TABLE policy_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    preset TEXT NOT NULL DEFAULT 'supervised'
        CHECK (preset IN ('autonomous', 'supervised', 'strict')),
    batch_window_seconds REAL NOT NULL DEFAULT 5.0
);

CREATE TABLE path_rules (
    id TEXT PRIMARY KEY,
    path_pattern TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL CHECK (tier IN ('observe', 'checkpoint', 'gate')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE action_rules (
    id TEXT PRIMARY KEY,
    match_pattern TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('observe', 'checkpoint', 'gate')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE cost_rules (
    id TEXT PRIMARY KEY,
    condition TEXT NOT NULL,
    promote_to TEXT NOT NULL CHECK (promote_to IN ('checkpoint', 'gate')),
    threshold_value REAL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE mcp_server_configs (
    name TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    args_json TEXT,
    env_json TEXT,
    contained BOOLEAN NOT NULL DEFAULT FALSE,
    reversible BOOLEAN NOT NULL DEFAULT FALSE,
    trusted BOOLEAN NOT NULL DEFAULT FALSE,
    tool_overrides_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE trust_grants (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    kinds_json TEXT NOT NULL,
    path_pattern TEXT,
    excludes_json TEXT,
    command_pattern TEXT,
    mcp_server TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
```

### Trail Node Columns

Each trail node (audit log entry) carries classification metadata:

```sql
tier TEXT;
reversible BOOLEAN;
contained BOOLEAN;
tier_reason TEXT;
checkpoint_ref TEXT;
rollback_status TEXT;
```

### Export and Import

For portability between instances:

```text
GET  /settings/policy/export  → JSON blob (all rules + mcp configs + presets)
POST /settings/policy/import  ← JSON blob, upserts
```

If version-controlled config is desired, export the JSON and commit it manually.

## API Surface

### Policy CRUD

```text
GET    /settings/policy                       Full policy state
PUT    /settings/policy/preset                Update preset

POST   /settings/policy/path-rules            Create path rule
PUT    /settings/policy/path-rules/{id}       Update path rule
DELETE /settings/policy/path-rules/{id}       Delete path rule

POST   /settings/policy/action-rules          Create action rule
PUT    /settings/policy/action-rules/{id}     Update action rule
DELETE /settings/policy/action-rules/{id}     Delete action rule

POST   /settings/policy/cost-rules            Create cost rule
PUT    /settings/policy/cost-rules/{id}       Update cost rule
DELETE /settings/policy/cost-rules/{id}       Delete cost rule
```

### MCP Servers

```text
GET    /settings/mcp-servers                  List all
POST   /settings/mcp-servers                  Add server (two-click flow)
PUT    /settings/mcp-servers/{name}           Update properties
DELETE /settings/mcp-servers/{name}           Remove server
```

### Trust Grants

```text
GET    /settings/trust-grants                 List active grants
POST   /settings/trust-grants                 Create grant
DELETE /settings/trust-grants/{id}            Revoke grant
```

### Utilities

```text
GET    /settings/policy/preview?pattern=...   Preview glob match against repo files
POST   /settings/policy/test-action           Test regex against recent shell history
GET    /settings/policy/suggestions           Suggest rules from job history
GET    /settings/policy/export                Export all config as JSON
POST   /settings/policy/import                Import JSON config
```

### Job-Level Approval

```text
POST   /jobs/{id}/approvals/{batch_id}/approve      Approve batch (all or partial)
POST   /jobs/{id}/approvals/{batch_id}/reject       Reject batch
POST   /jobs/{id}/approvals/{batch_id}/rollback     Rollback to pre-batch checkpoint
POST   /jobs/{id}/approvals/{action_id}/trust       Approve + create trust grant
```

## Router

Central routing function: classify, check trust, decide.

```python
async def route(action: Action, policy: RepoPolicy, trust_store: TrustStore) -> Decision:
    # 1. Classify
    reversible, contained = classify_properties(action)
    tier = resolve_tier(reversible, contained, policy)

    # 2. Observe/checkpoint: no interruption needed
    if tier == Tier.observe:
        return Decision(tier=tier, proceed=True)

    if tier == Tier.checkpoint:
        checkpoint_ref = await checkpoint_service.create(action)
        return Decision(tier=tier, proceed=True, checkpoint_ref=checkpoint_ref)

    # 3. Gate tier: check trust grants
    if trust_store.covers(action):
        checkpoint_ref = await checkpoint_service.create(action)
        return Decision(tier=tier, proceed=True, checkpoint_ref=checkpoint_ref, trusted=True)

    # 4. Gate tier, no trust: submit to batcher, block until operator decides
    checkpoint_ref = await checkpoint_service.create(action)
    resolution = await batcher.submit_and_wait(action, checkpoint_ref)

    return Decision(
        tier=tier,
        proceed=resolution.approved,
        checkpoint_ref=checkpoint_ref,
        batch_id=resolution.batch_id,
    )
```

Policy is loaded from the DB once at job start via `PolicyRepository.load()`,
cached in memory, and reloaded when settings change mid-job. Any mutation to
policy config, rules, MCP server configs, or trust grants publishes a
`PolicySettingsChanged` domain event. The runtime service subscribes, reloads
the `RepoPolicy` from DB, and pushes it into the adapter for every running job.
This ensures operators can tighten or relax policy while jobs are in progress
without waiting for a restart.

## Settings UI

### Preset Selector

```text
┌─────────────────────────────────────────────────────────────────┐
│  Settings → Approval Policy                                      │
│                                                                 │
│  Preset:  (●) Autonomous  ( ) Supervised  ( ) Strict           │
│                                                                 │
│  autonomous: Agent runs freely. Only gates actions that leave   │
│  the local environment (network, external APIs).                │
└─────────────────────────────────────────────────────────────────┘
```

### Rules Form

```text
┌─────────────────────────────────────────────────────────────────┐
│  Path Rules                                                      │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Pattern: [migrations/**/*.sql    ]  Tier: [gate ▼]      │   │
│  │ Reason:  [Schema changes need review]                    │   │
│  │                                                         │   │
│  │ Preview: 3 files match                                  │   │
│  │   migrations/0001_initial.sql                           │   │
│  │   migrations/0002_add_users.sql                         │   │
│  │   migrations/0003_add_roles.sql                         │   │
│  │                                          [Save] [Cancel]│   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  │ src/generated/**  →  observe  (auto-generated, safe)    [✎]│ │
│  │ .env*             →  gate     (secrets)                 [✎]│ │
│                                                                 │
│  [+ Add path rule]                                              │
│                                                                 │
│  Action Rules                                                    │
│                                                                 │
│  │ rm -rf *          →  gate     (destructive)             [✎]│ │
│  │ docker push.*     →  gate     (publishes image)         [✎]│ │
│                                                                 │
│  [+ Add action rule]                                            │
│                                                                 │
│  Cost Rules                                                      │
│                                                                 │
│  │ daily spend > $5  →  gate     (budget control)          [✎]│ │
│                                                                 │
│  [+ Add cost rule]                                              │
│                                                                 │
│  [Export rules]  [Import rules]                                  │
└─────────────────────────────────────────────────────────────────┘
```

### MCP Server Setup

```text
┌─────────────────────────────────────────────────────────────────┐
│  Settings → MCP Servers                                          │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ linear-mcp                                     [✎] [✕] │   │
│  │ npx @linear/mcp-server                                  │   │
│  │ contained: No   reversible: No   → gate (supervised)   │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ filesystem-mcp                                 [✎] [✕] │   │
│  │ npx @modelcontextprotocol/filesystem                    │   │
│  │ contained: Yes  reversible: Yes  → observe              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [+ Add MCP server]                                             │
└─────────────────────────────────────────────────────────────────┘
```

### Add MCP Server Dialog

```text
┌─────────────────────────────────────────────────────────────────┐
│  Add MCP Server                                                  │
│                                                                 │
│  Name:    [linear-mcp            ]                              │
│  Command: [npx @linear/mcp-server]                              │
│                                                                 │
│  ☐ Can actions be undone?              (reversible)             │
│  ☐ Stays within local environment?     (contained)              │
│                                                                 │
│  [Add server]                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Timeline Integration

The job timeline shows all actions with their tier as a visual indicator:

```text
┌────────────────────────────────────────────────────────────────┐
│ Timeline                                                        │
│                                                                │
│ ○ Read src/config.py                              observe      │
│ ○ Read src/models.py                              observe      │
│ ◐ Wrote src/models.py (+15 -3)                    checkpoint   │
│ ◐ Wrote migrations/0005.sql                       checkpoint   │
│ ● npm publish                                     gate ⏳      │
│   └─ "Publishes to registry (uncontained)"                     │
└────────────────────────────────────────────────────────────────┘
```

Symbols: `○` = observe, `◐` = checkpoint, `●` = gate.
Gate actions show their reason and pending/approved/rejected state.

## Implementation Phases

| Phase | Deliverable | Dependencies |
|-------|------------|--------------|
| 1 | DB schema (alembic migration) + PolicyRepository | none |
| 2 | Classifier module (properties + tier resolution) | Phase 1 |
| 3 | Shell classifier (POSIX + PS + cmd) | none |
| 4 | Router | Phases 1, 2 |
| 5 | CheckpointService | none |
| 6 | TrustStore + TrustGrant CRUD | Phase 1 |
| 7 | ApprovalBatcher | Phase 4 |
| 8 | Settings API (policy CRUD endpoints) | Phase 1 |
| 9 | MCP server config API + classification hook | Phases 1, 2 |
| 10 | Notification inbox (frontend) | Phases 7, 8 |
| 11 | Settings UI (frontend) | Phases 8, 9 |
| 12 | Timeline tier indicators (frontend) | Phase 4 |
| 13 | Export/Import endpoints | Phase 8 |

## Design Rationale

### Why DB instead of a config file in the worktree

* The UI does form-based CRUD through API endpoints. Writing to a file is fighting
  the persistence model.
* The agent works in the worktree. Writing config files mid-job creates merge
  conflicts with the agent's own commits.
* Rules belong to the CodePlane instance, not the repository. Cloning the repo
  elsewhere should not carry operator preferences.
* Export/import provides explicit portability when needed.

### Why two booleans instead of numeric risk scores

* Binary properties are observable: you can answer "is this reversible?" from the
  action's definition. You cannot answer "how risky is this on a scale of 1-10?"
  without subjective judgment.
* Two booleans produce four cells. Four cells map cleanly to three tiers. No
  thresholds to tune, no disagreements about what score constitutes "risky."
* Rules override at the tier level, not by adjusting a score. The operator says
  "gate this" or "observe this," not "add 3 risk points."

### Why three tiers

* Observe is "don't interrupt me." Gate is "stop and ask." Checkpoint is the
  middle ground: "take a savepoint so I can undo this later, but don't stop."
* A fourth tier would be "gate but you really mean it." The operator controls
  interruption through preset + trust grants. A tier beyond gate adds complexity
  without expressiveness.

### Why server-level MCP classification

* Tool annotations are not guaranteed by MCP servers.
* Even when present, annotations describe capability (read-only, destructive) but
  not containment (does it hit an external API?).
* Two questions at setup time cover the entire server. Per-tool overrides are
  available for refinement but not required.
