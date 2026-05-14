# Sidecar session tooling and permissions: audit and design

## Status: proposal draft

---

## Part 1 — Audit findings

### 1.1 Sidecars have no tool access at all

`SidecarSession.complete()` calls `adapter.complete()`, which is a single-turn HTTP completion. No SDK session is created, no tools are registered, no permission callbacks fire. Sidecars are text-in/text-out completers.

This is fine for the built-in trio (arbiter, planner, enricher) because they only need to reason about context and emit structured text. But it makes the entire "custom sidecar" system unable to do anything beyond text generation — no reading files, no running commands, no calling MCP tools.

### 1.2 No permission model for sidecar output routes

Custom sidecars can route output through four channels:

| Route | What it does | Risk |
|---|---|---|
| `event_bus` | Publish arbitrary DomainEvent | Low — events are internal signals |
| `job_metadata` | Overwrite job title/description | Low — cosmetic |
| `agent_message` | Inject system message into main agent context | **High** — controls what the main agent sees and does |
| `gate` | Emit verdict that claims to block the agent | **Medium** — see 1.3 |

`agent_message` is the most dangerous: a custom sidecar can inject arbitrary instructions into the main agent's context with `role=system`. There is no validation, no approval, no operator visibility beyond the `sidecar_agent_message` SSE event. The main agent has no way to distinguish a sidecar injection from a real system prompt.

**No rate limiting** on output routes. A sidecar with a `timer` condition (built-in only, but the concern generalizes to fast event triggers) could flood the agent with injected messages.

### 1.3 Gate route does not actually gate

The `GateRoute` publishes a `sidecar_gate_verdict` DomainEvent. But nothing in the pipeline actually pauses the main agent in response. For managed sessions, the agent SDK continues executing. For CLI sessions, the hook response would need to return a block decision, but the gate verdict event is not wired to any hook response path.

The gate route is a UI notification, not a control mechanism.

### 1.4 Custom sidecar validation is surface-level

`template_service._validate_definition()` checks that context sources, output routes, and conditions are in the allowed sets. But it does not validate:

- **Prompt template content** — a custom sidecar can instruct the LLM to produce output that, when routed via `agent_message`, hijacks the main agent.
- **Output parser + route combinations** — a `JsonObject` parser feeding an `EventBusRoute` can publish events with arbitrary payload shapes that other subscribers may not expect.
- **Model override** — custom sidecars can set `model` to any string. No validation against available models.

### 1.5 Context source boundaries are too wide for some use cases

`recent_messages` gives the sidecar the last N transcript entries, which may include tool results containing secrets (API keys in environment, file contents with credentials). The sidecar then sends this to a (possibly different) LLM endpoint. There is no redaction or filtering.

### 1.6 No per-sidecar preset/permission override

All sidecars for a job inherit the job's preset. An operator cannot say "the enricher can see everything but the custom security-reviewer sidecar should only see diffs." There is no field on `SidecarDefinition` or `SidecarConfig` for a permission tier.

This is moot today because sidecars have no tools, but becomes relevant if sidecars gain tool access (Part 2).

---

## Part 2 — Sidecar tooling design

### 2.1 The case for tool-using sidecars

Use cases that require tool access:

1. **Security reviewer** — reads files to check for hardcoded secrets, runs `grep` or static analysis.
2. **Test runner** — executes `pytest` on changed files after the agent finishes a step.
3. **Dependency auditor** — runs `npm audit` or `pip-audit` after package changes.
4. **Documentation generator** — reads source files, generates/updates docs.
5. **Linter/formatter** — runs tools and commits fixes.

All of these need to read files at minimum. Some need shell access. None of them need the full agent SDK — they need a controlled subset of tools.

### 2.2 Proposed: tool-scoped sidecar sessions

Add a new sidecar lifetime/capability tier: **agentic sidecars**.

```python
@dataclass(frozen=True)
class SidecarDefinition:
    # ... existing fields ...
    
    # NEW: tool access control
    tools: SidecarToolPolicy | None = None  # None = text-only (current behavior)
```

```python
@dataclass(frozen=True)
class SidecarToolPolicy:
    """Declares what tools a sidecar can use."""
    
    # Allowlist of tool categories (not individual tools)
    allowed_categories: frozenset[str]  # {"read", "search", "shell_readonly"}
    
    # Explicit tool blocklist (overrides categories)
    blocked_tools: frozenset[str] = frozenset()
    
    # MCP server access (empty = none)
    mcp_servers: frozenset[str] = frozenset()
    
    # Path restrictions (empty = job worktree only)
    allowed_paths: tuple[str, ...] = ()
    
    # Shell constraints
    shell_readonly: bool = True  # if shell allowed, only read commands
    shell_allowlist: tuple[str, ...] = ()  # explicit command prefixes
    
    # Max concurrent tool calls
    max_concurrent_tools: int = 1
    
    # Cost ceiling per pipeline execution (USD)
    max_cost_per_execution: float | None = None
```

**Tool categories** (coarse-grained, not per-tool):

| Category | What it includes | Risk |
|---|---|---|
| `read` | Read files, list directories, search content | Low |
| `search` | Semantic search, grep, file search | Low |
| `shell_readonly` | Shell commands that don't modify state | Medium |
| `shell_write` | Shell commands that modify files | High |
| `write` | File write, file create, file delete | High |
| `mcp` | MCP tool calls (scoped by `mcp_servers`) | Varies |

### 2.3 Implementation approach

Agentic sidecars would use `adapter.create_session()` + `adapter.stream_events()` instead of `adapter.complete()`. The session would be created with a `SessionConfig` that has:

- `disallowed_tools` populated from the inverse of `SidecarToolPolicy.allowed_categories`
- `protected_paths` from the tool policy
- `max_turns` from the sidecar definition
- `blocking_permission_handler` wired to a sidecar-specific policy router

The sidecar-specific policy router would be a stripped-down version of the main `PolicyRouter`:

- No monitor (no LLM evaluation of tool calls — too expensive for sidecars)
- No batcher (no human approval — defeats the purpose of automation)
- Hard allowlist/blocklist only
- Immediate deny for anything outside the policy

```python
class SidecarPolicyRouter:
    """Lightweight policy router for agentic sidecars."""
    
    async def route(self, action: Action, policy: SidecarToolPolicy) -> Decision:
        # 1. Category check
        category = classify_tool_category(action)
        if category not in policy.allowed_categories:
            return Decision(proceed=False, reason=f"category {category} not allowed")
        
        # 2. Explicit blocklist
        if action.tool_name in policy.blocked_tools:
            return Decision(proceed=False, reason=f"tool {action.tool_name} blocked")
        
        # 3. Path check (for file operations)
        if action.path and not within_allowed_paths(action.path, policy.allowed_paths):
            return Decision(proceed=False, reason="path outside allowed scope")
        
        # 4. Shell allowlist (for shell operations)
        if category in ("shell_readonly", "shell_write"):
            if not matches_shell_allowlist(action.command, policy.shell_allowlist):
                return Decision(proceed=False, reason="command not in allowlist")
        
        return Decision(proceed=True)
```

### 2.4 Custom sidecar safety tiers

Reuse the job preset concept but scope it to sidecars:

| Tier | Tool access | Approval | Use case |
|---|---|---|---|
| `text_only` | None (current behavior) | N/A | Arbiter, planner, enricher, title generator |
| `read_only` | Read files, search, list dirs | None | Security scanner, code reviewer |
| `shell_restricted` | Read + allowlisted shell commands | None | Test runner, linter, auditor |
| `agentic` | Full tool policy from definition | Sidecar gate prompt | General-purpose automation |

For custom sidecars created via the template API, restrict to `text_only` and `read_only` by default. `shell_restricted` and `agentic` require explicit operator opt-in (the `SidecarToolPolicy` must be present in the definition and the operator must approve it).

### 2.5 Hardening agent_message injection

Regardless of tool access, `agent_message` injection needs guardrails:

1. **Label prefix** — all injected messages MUST carry a visible label like `[sidecar:security-reviewer]`. The main agent's system prompt should document that these are sidecar opinions, not operator commands.
2. **Rate limit** — max 1 injection per sidecar per N seconds (configurable, default 60s). Prevents flooding.
3. **Content length cap** — injected messages truncated to a configurable limit (prevents context window exhaustion).
4. **Operator visibility** — the frontend should surface sidecar injections in the transcript with distinct styling, not mixed into the agent's messages.

---

## Part 3 — Permissions for CLI (imported) sessions

### 3.1 Current state

Imported sessions have zero permission enforcement:

- **Claude CLI**: Only the Stop hook is registered. The `PreToolUse` hook is not registered, so every tool call proceeds without CodePlane knowing about it in advance.
- **Copilot CLI**: No hook mechanism exists. Tool calls are observed post-hoc via OTEL spans.

### 3.2 What's possible per SDK

| Capability | Claude CLI | Copilot CLI |
|---|---|---|
| See tool calls before execution | Yes (PreToolUse hook) | No |
| Block tool calls | Yes (return `{"decision":"deny"}`) | No |
| See tool results after execution | Yes (PostToolUse hook + JSONL) | Yes (OTEL spans) |
| Inject messages | Yes (Stop hook response) | Yes (Steer API) |
| Abort session | Yes (process signal) | Yes (Steer API) |
| Real-time event stream | Yes (JSONL tail) | Yes (OTEL file tail) |

### 3.3 Design: tiered permission enforcement for CLI sessions

#### Tier 1 — Observation only (Copilot CLI + Claude CLI)

This is what exists today. CodePlane watches tool calls after they happen and surfaces them in the UI. No blocking, no approval.

**Improvements needed:**
- Classify observed tool calls through the same `action_policy.classifier` used for managed sessions. Surface the classification (tier, reversibility, containment) in the transcript UI so the operator can see what's risky.
- Flag actions that WOULD have been gated under the job's preset. Show these as "would-gate" indicators in the UI.
- Enable sidecar triggers on classified actions (e.g., fire security-reviewer sidecar when a `gate`-tier action is observed).

#### Tier 2 — Advisory gates (Claude CLI only)

Register the `PreToolUse` hook with Claude CLI. On each tool call:

1. Run `action_policy.classifier.classify()` against the action.
2. If tier is `observe` or `checkpoint`: return `{}` (allow).
3. If tier is `gate`: **depends on mode**:
   - **Advisory mode** (default): return `{}` (allow), but publish `approval_advisory` event. The UI shows a warning badge. Sidecar gate routes can fire.
   - **Blocking mode** (opt-in): return `{"decision":"deny","reason":"CodePlane gate: <reason>"}`. Publish `approval_requested` event. Wait for operator resolution via the next Stop hook cycle.

**Blocking mode** has a latency problem: Claude CLI calls PreToolUse synchronously. If we deny, the agent gets the denial immediately — no round-trip wait. But if we want to ask the operator and then allow, we have to deny first and hope the agent retries (it will, Claude CLI retries denied tools on the next turn). This is workable but not instant.

**Implementation sketch:**

```python
# backend/api/hooks.py — new endpoint

@router.post("/hooks/claude/pre-tool-use")
async def claude_pre_tool_use_hook(
    request: Request,
    watcher: FromDishka[ClaudeSessionStateWatcher],
    policy_router: FromDishka[PolicyRouter],
) -> JSONResponse:
    body = await request.json()
    session_id = body.get("session_id", "")
    tool_name = body.get("tool_name", "")
    tool_input = body.get("tool_input", {})
    
    job = watcher.get_job_for_session(session_id)
    if not job:
        return JSONResponse(content={})
    
    # Build action from hook payload
    action = Action.from_claude_hook(job.id, tool_name, tool_input)
    
    # Classify
    repo_policy = await get_repo_policy(job.repo)
    classification = classify(action, repo_policy)
    
    # Publish classification event (always, for UI visibility)
    await event_bus.publish(action_classified_event(job.id, action, classification))
    
    if classification.tier == Tier.gate and repo_policy.cli_gate_mode == "blocking":
        return JSONResponse(content={
            "decision": "deny",
            "reason": f"CodePlane gate: {classification.reason}",
        })
    
    return JSONResponse(content={})
```

**Claude CLI settings registration** (add PreToolUse hook alongside Stop hook):

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "curl -s -X POST http://localhost:PORT/api/hooks/claude -H 'Content-Type: application/json' -d @-"
      }
    ],
    "PreToolUse": [
      {
        "type": "command",
        "command": "curl -s -X POST http://localhost:PORT/api/hooks/claude/pre-tool-use -H 'Content-Type: application/json' -d @-"
      }
    ]
  }
}
```

#### Tier 3 — Full supervision (Claude CLI, blocking mode)

Same as Tier 2 blocking mode but with:

- Deny + queue for human approval on `gate`-tier actions.
- Create checkpoint before `checkpoint`-tier actions.
- The operator resolves via the existing approval UI.
- On next agent turn (after denial), the watcher checks if the approval was granted and queues an operator message: "The previously denied action has been approved. Please retry."
- Track denied-then-approved cycles to auto-create trust grants (same as managed sessions).

**Latency concern**: Claude CLI's PreToolUse hook is synchronous with a timeout. We can't hold the connection open waiting for human approval — we must deny immediately and handle the retry cycle. This is fundamentally different from managed sessions where the SDK blocks on the permission callback.

#### Copilot CLI — observation is the ceiling

Copilot CLI has no pre-execution hook. The best we can do:

1. Post-hoc classification of OTEL tool spans.
2. Surface "would-gate" warnings in the UI.
3. If a dangerous action is detected, immediately send a steer message: "WARNING: You just executed [action] which would be gated under your supervision policy. Consider reverting."
4. Fire sidecar triggers on dangerous classifications.

This is Tier 1 with better UX — not true permission enforcement.

### 3.4 Sidecars in CLI sessions

Sidecars already work for CLI sessions (`register_external_session()` opens the built-in trio). But:

**What works:**
- Built-in sidecars (arbiter, planner, enricher) function identically — they consume DomainEvents from the bus and the bus is fed by the watchers.
- Custom sidecars with event/threshold/regex/content triggers work because those triggers match DomainEvents published by the watchers.

**What doesn't work:**
- **Gate routes** are purely informational — no mechanism to actually pause the CLI agent.
  - Claude CLI fix: Wire gate verdicts into the pending-message queue. On the next Stop hook, return the gate verdict as a block decision.
  - Copilot CLI fix: Send gate verdict via Steer API as a warning message.
- **Agent message injection** is delayed for CLI sessions:
  - Claude CLI: queued in pending messages, delivered on next Stop hook. The agent may execute several tool calls before seeing the injected message.
  - Copilot CLI: sent via Steer API with ~3s latency. Not synchronous.
- **Manual trigger** has no API path for CLI sessions — the `POST /api/sidecars/{name}/trigger` endpoint isn't wired for imported jobs.

**What's different about sidecar context for CLI sessions:**
- `recent_messages` context provider works (watchers publish transcript events).
- `job_diff` works (DiffService is registered for imported sessions).
- `job_prompt` works for Claude CLI (prompt captured from UserPromptSubmit). Does NOT work for Copilot CLI (prompt stays as placeholder).
- `active_tool` partially works — tool tracking happens, but there's no "waiting for approval" state for CLI sessions.

### 3.5 Recommendation matrix

| Feature | Managed | Claude CLI | Copilot CLI | Priority |
|---|---|---|---|---|
| Tool call classification in UI | Have | Build (Tier 1) | Build (Tier 1) | P0 |
| "Would-gate" indicators | N/A | Build (Tier 1) | Build (Tier 1) | P0 |
| PreToolUse hook registration | N/A | Build (Tier 2) | N/A | P1 |
| Advisory gate mode | N/A | Build (Tier 2) | N/A | P1 |
| Blocking gate mode | N/A | Build (Tier 3) | N/A | P2 |
| Sidecar gate → Stop hook | N/A | Build | N/A | P1 |
| Sidecar gate → Steer API | N/A | N/A | Build | P1 |
| Post-hoc steer warning on danger | N/A | N/A | Build (Tier 1) | P1 |
| Per-sidecar tool policy | Build | Build | Build | P2 |
| agent_message rate limiting | Build | Build | Build | P1 |
| Sidecar-specific permission tier | Build | Build | Build | P2 |

---

## Part 4 — Implementation plan

### Phase 1: Classification and visibility (all session types)

1. Add `action_policy.classifier.classify()` call to `feed_external_event()` for every tool_call event. Attach classification to the transcript DomainEvent payload.
2. Add `action_classified` event kind. Publish for both managed and imported tool calls.
3. Frontend: render classification badges on tool call transcript entries.
4. Frontend: add "would-gate" warning indicator for CLI sessions when tier is `gate`.

### Phase 2: Claude CLI PreToolUse hook

1. Add `POST /api/hooks/claude/pre-tool-use` endpoint.
2. Wire `Action.from_claude_hook()` to build an `Action` from hook payload.
3. Classify and publish event.
4. Advisory mode: always allow, surface in UI.
5. Update `ClaudeSessionStateWatcher._configure_hooks()` to register PreToolUse hook.
6. Add `cli_gate_mode` to repo config (`advisory` | `blocking`, default `advisory`).

### Phase 3: Gate route enforcement for CLI sessions

1. Claude CLI: wire `sidecar_gate_verdict` events into the pending-message queue for the session. On next Stop hook, return as block decision.
2. Copilot CLI: wire `sidecar_gate_verdict` events into Steer API message delivery.
3. Add timeout handling — if the agent doesn't hit the Stop hook within `gate.timeout_s`, the gate verdict expires.

### Phase 4: agent_message hardening

1. Add mandatory `[sidecar:<name>]` label prefix to all injected messages.
2. Add per-sidecar rate limiter for `agent_message` output route.
3. Add content length cap to sidecar prompt template rendering.
4. Frontend: distinct visual treatment for sidecar-injected transcript entries.

### Phase 5: Tool-using sidecars

1. Add `SidecarToolPolicy` to `SidecarDefinition`.
2. Implement `SidecarPolicyRouter` (allowlist-only, no LLM monitor, no human approval).
3. Modify `SidecarSession` to optionally use `adapter.create_session()` + `adapter.stream_events()` instead of `adapter.complete()`.
4. Add tool category validation to `template_service._validate_definition()`.
5. Update standby pool to support agentic sessions (heavier, fewer pooled).
6. Add `agentic_sidecar_max_concurrent` config option to limit resource usage.

### Phase 6: Per-sidecar permission tiers

1. Add `preset: Preset | None` field to `SidecarDefinition` (None = inherit from job).
2. Wire sidecar preset into `SidecarPolicyRouter`.
3. Template validation: `agentic` tier requires explicit operator opt-in.

---

## Appendix A — Threat model for sidecar injection

| Attack vector | Current risk | Mitigation |
|---|---|---|
| Custom sidecar prompt instructs LLM to emit agent-hijacking output | High | Phase 4: label prefix, rate limit, content cap |
| Custom sidecar publishes malformed events via EventBusRoute | Medium | Validate event payload schema in dispatcher before publishing |
| Custom sidecar exhausts LLM budget via rapid triggers | Medium | Add per-sidecar cost ceiling, enforce in dispatcher |
| Sidecar context leaks secrets from tool results | Medium | Add redaction filter to `recent_messages` context provider |
| Agentic sidecar escapes path restrictions | Low (if implemented correctly) | Hard containment via adapter's `protected_paths` + `disallowed_tools` |

## Appendix B — CLI session capability matrix (current vs proposed)

| Capability | Managed (current) | Claude CLI (current) | Claude CLI (proposed) | Copilot CLI (current) | Copilot CLI (proposed) |
|---|---|---|---|---|---|
| Pre-execution tool gate | Yes | No | Yes (Tier 2/3) | No | No (impossible) |
| Post-execution classification | Yes | No | Yes (Tier 1) | No | Yes (Tier 1) |
| Sidecar gate enforcement | Partial (event only) | No | Yes (Stop hook) | No | Warning only (Steer) |
| Operator approval flow | Yes | No | Yes (blocking mode) | No | No |
| Sidecar agent_message | Immediate | Delayed (Stop hook) | Delayed (Stop hook) | Delayed (Steer ~3s) | Delayed (Steer ~3s) |
| Trust grant accumulation | Yes | No | Yes (Tier 3) | No | No |
| Cost controls | Yes | No | Yes (Tier 2+) | No | Post-hoc warning only |
