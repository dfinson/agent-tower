# Sidecar session specification

## Premise

A sidecar session is not a type hierarchy. It is **one type of object with
different configuration**. The built-in arbiter, planner, enricher, and
title generator are hardcoded instances. Custom sidecars are the same object
loaded from the database. Same dispatcher, same execution path, same
lifecycle. The only difference is where the definition came from.

## The object

Every sidecar is an instance of `SidecarDefinition`:

```python
@dataclass(frozen=True)
class SidecarDefinition:
    # --- Identity ---
    name: str                               # unique per job
    phase: SidecarPhase                     # preflight | midflight | postflight
    lifetime: SidecarLifetime               # ephemeral | windowed | persistent
    model: str | None = None                # None → DEFAULT_UTILITY_MODEL
    system_prompt: str = ""
    max_turns: int | None = None            # windowed expiry
    timeout_s: float | None = None          # windowed expiry
    session_kind: SessionKind = "sidecar"   # telemetry dimension
    gate: str | None = None                 # job field name; if field is False, skip

    # --- Trigger pipeline ---
    triggers: tuple[TriggerPipeline, ...] = ()
```

That's the entire type. Built-ins and customs are instances of this.

## Trigger pipeline

Each trigger pipeline is a complete unit of work: a condition that decides
when to fire, a context assembly that gathers input, a prompt template, an
output parser, and an output route.

```python
@dataclass(frozen=True)
class TriggerPipeline:
    condition: TriggerCondition             # WHEN to fire
    context_sources: tuple[str, ...] = ()   # WHAT data to gather (provider names)
    prompt_template: str = ""               # template with {variable} placeholders
    output_parser: OutputParser = PlainText()
    output_routes: tuple[OutputRoute, ...] = ()
    concurrency: Concurrency = Concurrency.skip_if_running
```

This is the only pipeline. There are no special code paths for arbiter vs
planner vs enricher. The dispatcher runs the same sequence for all of them:

```
condition met?
  → gather context from providers
  → if any required context is None, skip
  → render prompt_template with context dict
  → call session.complete(rendered_prompt)
  → parse response with output_parser
  → route parsed result through output_routes
```

## Trigger conditions

Seven kinds. All parametrized. No handler functions.

```python
@dataclass(frozen=True)
class EventCondition:
    """Fires when a matching DomainEvent is published."""
    event_kinds: tuple[DomainEventKind, ...]
    event_filter: dict[str, str] = field(default_factory=dict)  # payload key=value
    once: bool = False                      # fire only the first time per session

@dataclass(frozen=True)
class TimerCondition:
    """Fires on a periodic interval, optionally gated by idle time."""
    interval_s: float                       # min seconds between firings
    idle_guard_s: float | None = None       # only fire after this much inactivity

@dataclass(frozen=True)
class ThresholdCondition:
    """Fires when a counter crosses a value."""
    metric: str                             # "tool_calls" | "messages" | "tokens"
    value: int
    once: bool = False                      # fire once then deactivate

@dataclass(frozen=True)
class ManualCondition:
    """Fires on explicit API call."""
    pass

@dataclass(frozen=True)
class RegexCondition:
    """Fires when agent output matches a regex pattern.

    The dispatcher applies the pattern against each new agent message.
    Named capture groups are injected into the trigger context as
    template variables (in addition to the standard context sources).
    """
    pattern: str                            # Python-flavored regex
    source: str = "messages"                # "messages" | "tool_calls" | "tool_output"
    once: bool = False                      # fire only the first match

@dataclass(frozen=True)
class FilePatternCondition:
    """Fires when changed files match a glob pattern.

    Evaluated after each tool call that modifies the worktree. The
    dispatcher diffs the working tree and tests each changed path
    against the pattern.
    """
    glob: str                               # e.g. "**/*.sql", "src/api/**"
    change_kind: str = "any"                # "any" | "added" | "modified" | "deleted"

@dataclass(frozen=True)
class ContentMatchCondition:
    """Fires when agent messages contain a substring or keyword.

    Simpler than RegexCondition for plain keyword detection.
    Case-insensitive by default.
    """
    keywords: tuple[str, ...]               # any match triggers
    case_sensitive: bool = False
    source: str = "messages"                # "messages" | "tool_calls" | "tool_output"
    once: bool = False

TriggerCondition = (
    EventCondition | TimerCondition | ThresholdCondition | ManualCondition
    | RegexCondition | FilePatternCondition | ContentMatchCondition
)
```

### Custom sidecar allowed conditions

Custom sidecars may use: `event`, `threshold`, `manual`, `regex`,
`file_pattern`, `content_match`. `timer` conditions are reserved for
built-in sidecars (they require a system-level tick loop).

## Context providers

A context provider is a registered async function that extracts data from
runtime state and returns a dict (or `None` to signal "skip this trigger").

```python
ContextProvider = Callable[[str], Awaitable[dict[str, Any] | None]]
# argument is job_id, return is template variables or None
```

Providers are registered at startup by the services that own the state:

| Provider name | Registered by | Returns | Returns None when |
|---|---|---|---|
| `active_tool` | RuntimeService | `{tool_name, elapsed_s, elapsed_human, tool_args}` | No tool active, or job waiting for approval |
| `job_prompt` | TrailService | `{task, first_msg}` | No job state, or no messages yet |
| `recent_messages` | TrailService | `{messages, tool_intents, tool_names}` | No job state |
| `pending_nodes` | TrailEnricher | `{nodes_json, goal_intent, recent_decisions}` | No pending nodes |
| `first_content` | TrailService | `{content}` | Already titled, or no content |
| `trigger_event` | Dispatcher | `{payload}` (from the triggering event) | — |
| `job_diff` | DiffService | `{diff}` | No diff available |

**Providers encapsulate guards.** The `active_tool` provider returns `None`
when the job is waiting for approval or no tool is active. The dispatcher
doesn't need to know about approval states — it just sees `None` and skips.
All the scattered guard conditions in `_check_stall()` today move into the
provider.

**Provider registration:**

```python
class SidecarDispatcher:
    def register_context(self, name: str, provider: ContextProvider) -> None: ...
```

RuntimeService at startup:
```python
dispatcher.register_context("active_tool", self._provide_active_tool)
```

## Output parsing

Parsers turn the raw LLM response string into structured data.

```python
@dataclass(frozen=True)
class PlainText:
    """Use the response as-is."""
    strip: bool = True

@dataclass(frozen=True)
class JsonObject:
    """Parse JSON, optionally validate required keys."""
    required_keys: tuple[str, ...] = ()

@dataclass(frozen=True)
class JsonArray:
    """Parse JSON array."""
    item_keys: tuple[str, ...] = ()         # expected keys per item

OutputParser = PlainText | JsonObject | JsonArray
```

If parsing fails, the dispatcher logs a warning and skips output routing.
No exception propagation.

## Output routing

Routes deliver the parsed result to a destination.

```python
@dataclass(frozen=True)
class EventBusRoute:
    """Publish a DomainEvent."""
    event_kind: DomainEventKind
    payload_mapping: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class JobMetadataRoute:
    """Write a field on the job record."""
    field_name: str                         # "title", "description", etc.

@dataclass(frozen=True)
class CallbackRoute:
    """Invoke a registered callback with the parsed result."""
    callback_name: str

@dataclass(frozen=True)
class ConditionalRoute:
    """Route only when a parsed field matches a value."""
    field: str
    value: str
    inner: OutputRoute                      # the actual route to use

OutputRoute = EventBusRoute | JobMetadataRoute | CallbackRoute | ConditionalRoute | AgentMessageRoute | GateRoute
```

### Agent interaction routes

Two additional route types allow sidecars to communicate with the primary
agent session directly.

```python
@dataclass(frozen=True)
class AgentMessageRoute:
    """Inject a system-level message into the primary agent's conversation.

    The parsed sidecar output becomes the message content. The agent sees it
    as a system/tool message on its next turn — it cannot distinguish it
    from platform-generated guidance.

    Use cases: mid-run course corrections, security warnings, style nudges,
    injecting review feedback the agent should act on.
    """
    role: str = "system"                    # "system" | "tool_result"
    label: str = ""                         # optional prefix: "[security-reviewer]"

@dataclass(frozen=True)
class GateRoute:
    """Block agent execution until the sidecar produces a verdict.

    When a trigger fires with a GateRoute, the dispatcher:
    1. Pauses the agent's session (holds the next tool-call or response)
    2. Runs the sidecar pipeline to completion
    3. Parses the verdict from the sidecar output
    4. If approved → resumes the agent
    5. If rejected → cancels the pending action and injects the rejection
       reason as a system message so the agent can course-correct

    The parsed output MUST contain a `verdict` field ("approve" | "reject")
    and an optional `reason` field.
    """
    verdict_field: str = "verdict"          # key in parsed output
    reason_field: str = "reason"            # key for rejection reason
    timeout_s: float = 30.0                 # max wait before auto-approve
```

**Availability:** Both `agent_message` and `gate` routes are available to
custom sidecars. They are the primary mechanism for user-defined sidecars to
influence agent behavior.

**Custom sidecar allowed output routes (updated):**
`event_bus`, `job_metadata`, `agent_message`, `gate`

`callback` routes remain reserved for built-in sidecars.

**Callbacks** are the escape hatch for complex output processing. The
planner needs to create `PlanStep` objects in `TrailJobState`. The enricher
needs to update trail nodes in the database. These are registered the same
way as context providers:

```python
class SidecarDispatcher:
    def register_callback(self, name: str, fn: OutputCallback) -> None: ...
```

## Concurrency control

```python
class Concurrency(StrEnum):
    skip_if_running = "skip_if_running"     # drop trigger if previous call still in flight
    queue = "queue"                         # buffer and execute after current call finishes
    parallel = "parallel"                   # allow concurrent calls (for stateless sidecars)
```

The dispatcher tracks `(job_id, sidecar_name) → in_flight` and enforces the
policy. This replaces the current `_stall_check_pending` set in
RuntimeService.

## The dispatcher

One object. Subscribes to EventBus. Runs timer ticks. Tracks threshold
counters. Executes trigger pipelines.

```python
class SidecarDispatcher:
    def __init__(
        self,
        session_manager: SidecarSessionManager,
        event_bus: EventBus,
    ) -> None: ...

    # --- Registration (called at startup) ---
    def register_context(self, name: str, provider: ContextProvider) -> None: ...
    def register_callback(self, name: str, fn: OutputCallback) -> None: ...

    # --- Job lifecycle ---
    def activate(self, job_id: str, definitions: list[SidecarDefinition]) -> None:
        """Open sidecars and register triggers for a job.
        Called by RuntimeService on job start.
        definitions = BUILTIN_SIDECARS merged with custom defs from CreateJobRequest.
        """

    async def deactivate(self, job_id: str) -> None:
        """Close all sidecars, flush metrics. Called on job terminal state."""

    # --- Trigger entry points ---
    async def handle_event(self, event: DomainEvent) -> None:
        """EventBus subscriber. Evaluates event conditions for all active sidecars."""

    async def tick(self) -> None:
        """Called from a periodic loop. Evaluates timer conditions."""

    def increment(self, job_id: str, metric: str, delta: int = 1) -> None:
        """Increment a threshold counter. Evaluates threshold conditions."""

    async def fire(self, job_id: str, sidecar_name: str, context: dict | None = None) -> None:
        """Manual trigger. Used by API endpoint."""

    # --- Postflight ---
    async def run_postflight(self, job_id: str) -> None:
        """Open and execute all postflight sidecars for a completed job."""
```

### Execution flow

Every trigger entry point converges to the same internal method:

```python
async def _execute_pipeline(
    self,
    job_id: str,
    definition: SidecarDefinition,
    pipeline: TriggerPipeline,
    extra_context: dict[str, Any] | None = None,
) -> None:
    # 1. Gate check
    if definition.gate and self._is_gated(job_id, definition.gate):
        return

    # 2. Concurrency check
    if not self._acquire(job_id, definition.name, pipeline.concurrency):
        return

    try:
        # 3. Assemble context
        ctx: dict[str, Any] = {}
        for source_name in pipeline.context_sources:
            provider = self._context_providers[source_name]
            result = await provider(job_id)
            if result is None:
                return  # required context missing → skip
            ctx.update(result)
        if extra_context:
            ctx.update(extra_context)

        # 4. Render prompt
        prompt = pipeline.prompt_template.format_map(ctx)

        # 5. Call LLM
        session = self._session_manager.get(job_id, definition.name)
        if session is None:
            return
        raw = await session.complete(prompt)

        # 6. Parse
        parsed = self._parse(raw, pipeline.output_parser)
        if parsed is None:
            return

        # 7. Route
        for route in pipeline.output_routes:
            await self._route(job_id, parsed, route)
    finally:
        self._release(job_id, definition.name)
```

That's it. No sidecar-specific code paths. No if-arbiter-do-X. The same 7
steps for every sidecar, built-in or custom.

## Phases

| Phase | When activated | When deactivated |
|---|---|---|
| **preflight** | `activate()` called, before primary agent starts | Primary agent session begins |
| **midflight** | Primary agent session begins | Job reaches terminal state |
| **postflight** | Job reaches terminal state | `run_postflight()` completes |

### Preflight execution

`RuntimeService.start_or_enqueue()`:
1. Calls `dispatcher.activate(job_id, definitions)`
2. Dispatcher opens all preflight sidecars
3. Dispatcher runs preflight trigger pipelines (sequentially, in definition order)
4. Preflight sidecars are closed
5. Primary agent session starts
6. Dispatcher opens midflight sidecars

### Postflight execution

On job terminal event:
1. Midflight sidecars are closed (metrics preserved)
2. `dispatcher.run_postflight(job_id)` opens postflight sidecars
3. Postflight trigger pipelines execute sequentially
4. Postflight sidecars are closed
5. `dispatcher.deactivate(job_id)` flushes all metrics

## Lifetimes

| Lifetime | Session behavior |
|---|---|
| **ephemeral** | Dispatcher creates a fresh session per pipeline execution. No conversation history. |
| **windowed** | Session persists until `max_turns` or `timeout_s` is exceeded, then the next trigger gets a fresh session. |
| **persistent** | Session persists for the entire phase duration. Full conversation history. |

## Model resolution

Per-sidecar. Resolution order:

1. `definition.model` (explicit on the definition)
2. Job-level `sidecar_model` override (from `CreateJobRequest`)
3. `DEFAULT_UTILITY_MODEL` (global config)

`SidecarSessionManager.open()` accepts a `model` parameter. The manager
maintains `dict[str, LightweightCompleter]` keyed by model name, creating
completers lazily.

## Built-in definitions

These are Python constants. They are the **only** built-in sidecar logic in
the codebase. Everything else flows through the parametrized pipeline.

### Arbiter (stall detection)

```python
BUILTIN_ARBITER = SidecarDefinition(
    name="arbiter",
    phase="midflight",
    lifetime="persistent",
    gate="enable_stall_detection",
    system_prompt=ARBITER_SYSTEM_PROMPT,
    triggers=(
        TriggerPipeline(
            condition=TimerCondition(
                interval_s=_STALL_RECHECK_INTERVAL_S,
                idle_guard_s=_STALL_CHECK_THRESHOLD_S,
            ),
            context_sources=("active_tool",),
            prompt_template=_STALL_ARBITER_PROMPT,
            output_parser=JsonObject(required_keys=("action", "reason")),
            output_routes=(
                ConditionalRoute(
                    field="action",
                    value="interrupt",
                    inner=CallbackRoute(callback_name="handle_stall_interrupt"),
                ),
            ),
            concurrency=Concurrency.skip_if_running,
        ),
    ),
)
```

**Context provider `active_tool`** (registered by RuntimeService):
- Returns `{tool_name, elapsed_human, tool_args}` from `_active_tool[job_id]`
- Returns `None` if: no active tool, job waiting for approval, elapsed <
  threshold

**Callback `handle_stall_interrupt`** (registered by RuntimeService):
- Current body of `_handle_stall_interrupt()` — cancels the tool, publishes
  stall event

### Planner (plan inference)

```python
BUILTIN_PLANNER = SidecarDefinition(
    name="planner",
    phase="midflight",
    lifetime="windowed",
    gate="enable_plan_tracking",
    system_prompt=PLANNER_SYSTEM_PROMPT,
    triggers=(
        TriggerPipeline(
            condition=ThresholdCondition(metric="messages", value=1, once=True),
            context_sources=("job_prompt",),
            prompt_template=INFER_PLAN_PROMPT,
            output_parser=JsonObject(required_keys=("items",)),
            output_routes=(
                CallbackRoute(callback_name="apply_inferred_plan"),
            ),
        ),
        TriggerPipeline(
            condition=ThresholdCondition(metric="tool_calls", value=3, once=True),
            context_sources=("job_prompt",),
            prompt_template=INFER_PLAN_PROMPT,
            output_parser=JsonObject(required_keys=("items",)),
            output_routes=(
                CallbackRoute(callback_name="apply_inferred_plan"),
            ),
        ),
    ),
)
```

**Context provider `job_prompt`** (registered by TrailService):
- Returns `{task, first_msg}` from `TrailJobState`
- Returns `None` if no job state or no prompt/messages

**Callback `apply_inferred_plan`** (registered by PlanManager):
- Takes parsed `{items: [...]}`, creates `PlanStep` objects, emits
  `plan_step_updated` events
- Current body of `PlanManager.infer_plan()` after the LLM call

**Note:** `feed_native_plan` is NOT a sidecar trigger. It is pure state
management (parsing the todo tool's output into plan steps). No LLM call, no
sidecar session. It stays in PlanManager, gated by
`_plan_tracking_disabled`.

### Enricher (trail enrichment)

```python
BUILTIN_ENRICHER = SidecarDefinition(
    name="enricher",
    phase="midflight",
    lifetime="ephemeral",
    system_prompt=ENRICH_SYSTEM_PROMPT,
    triggers=(
        TriggerPipeline(
            condition=TimerCondition(interval_s=config.enrich_interval_seconds),
            context_sources=("pending_enrichment",),
            prompt_template="{enrichment_prompt}",
            output_parser=JsonObject(),
            output_routes=(
                CallbackRoute(callback_name="apply_enrichment"),
            ),
            concurrency=Concurrency.skip_if_running,
        ),
    ),
)
```

**Context provider `pending_enrichment`** (registered by TrailEnricher):
- Queries `TrailNodeRepository.get_pending_enrichment()`
- Groups by job, builds prompts via `build_enrichment_prompt()`
- Returns `{enrichment_prompt}` or `None` if nothing pending
- The batching-by-job logic lives inside the provider

**Callback `apply_enrichment`** (registered by TrailEnricher):
- Parses enrichment response, updates trail nodes
- Current body of `drain_enrichment()` after the LLM call

**Scope note:** The enricher's context provider and callback need access to
the trail repository. They don't need the sidecar session or a job_id —
they operate across jobs. The dispatcher invokes this pipeline with a
synthetic job_id (e.g., `"__global__"`) and the enricher's context provider
ignores it.

Alternatively, the enricher stays as-is (background drain loop calling
`session_manager.complete()`) and is NOT modeled as a sidecar definition.
This is the pragmatic choice if the global-scope sidecar abstraction adds
more confusion than value.

### Title generator

```python
BUILTIN_TITLE_GEN = SidecarDefinition(
    name="title_generator",
    phase="midflight",
    lifetime="ephemeral",
    system_prompt="",  # prompt is self-contained in template
    triggers=(
        TriggerPipeline(
            condition=EventCondition(
                event_kinds=(DomainEventKind.transcript_updated,),
                event_filter={"role": "agent"},
                once=True,
            ),
            context_sources=("first_content",),
            prompt_template=(
                "Given this agent's first message, generate a concise "
                "3-8 word title for the coding task. Respond with ONLY "
                "the title text, no quotes, no punctuation at the end."
                "\n\nAgent message:\n{content}"
            ),
            output_parser=PlainText(),
            output_routes=(
                JobMetadataRoute(field_name="title"),
                EventBusRoute(
                    event_kind=DomainEventKind.job_title_updated,
                    payload_mapping={"title": "result"},
                ),
            ),
        ),
    ),
)
```

**Context provider `first_content`** (registered by TrailService):
- Returns `{content}` from the first agent message (truncated)
- Returns `None` if title already exists or auto-title already attempted

## Custom sidecars

Custom sidecars are `SidecarDefinition` instances constructed from the
`CreateJobRequest` payload and stored on the job record for resume support.

### API shape

```json
{
  "sidecars": [
    {
      "name": "security-reviewer",
      "phase": "postflight",
      "lifetime": "ephemeral",
      "model": "claude-sonnet-4-20250514",
      "systemPrompt": "You are a security code reviewer.",
      "triggers": [
        {
          "condition": {"kind": "manual"},
          "contextSources": ["job_diff"],
          "promptTemplate": "Review this diff:\n{diff}",
          "outputParser": {"kind": "json_object"},
          "outputRoutes": [
            {"kind": "event_bus", "eventKind": "sidecar_result"}
          ]
        }
      ]
    }
  ]
}
```

### Validation

- `name` must not collide with a built-in unless the definition also sets
  `"override": true`.
- Custom sidecars may use: `event`, `threshold`, `manual`, `regex`,
  `file_pattern`, `content_match` conditions.
  `timer` conditions are reserved for built-in sidecars (they require a
  system-level tick loop).
- `contextSources` for custom sidecars are restricted to a safe subset:
  `trigger_event`, `job_diff`, `job_prompt`, `recent_messages`. Providers
  that touch internal state (`active_tool`, `pending_enrichment`) are not
  exposed.
- `outputRoutes` for custom sidecars are restricted to: `event_bus`,
  `job_metadata`, `agent_message`, `gate`. `callback` routes are reserved
  for built-in sidecars.

### Overriding built-ins

```json
{
  "sidecars": [
    {
      "name": "planner",
      "override": true,
      "model": "claude-sonnet-4-20250514",
      "systemPrompt": "You are a senior engineering planner..."
    }
  ]
}
```

A custom definition with `override: true` and a built-in name replaces that
built-in entirely. Unspecified fields are NOT inherited from the built-in —
the override is a full replacement. If you want to change just the model,
you must also supply the triggers and prompt templates.

### Persistence

Custom sidecar definitions are serialized as JSON and stored on the
`JobRow`. On session resume, the dispatcher reconstructs definitions from
the stored JSON.

```
JobRow.sidecar_definitions: JSON | None
```

Saved sidecars are also stored in a user-level library
(`SidecarTemplateRow`) so they can be reused across jobs.

```
SidecarTemplateRow:
    id: str
    name: str               # human-readable, unique per user
    description: str         # short summary (auto-generated from prompt)
    definition_json: JSON    # full SidecarDefinition serialized
    created_at: datetime
    last_used_at: datetime | None
```

### Creation UX

Custom sidecars are added in two places:

1. **Pre-job** — "Advanced options" section of the job creation screen
2. **Settings** — a sidecar library page for managing saved definitions

Both share the same creation flow:

**Step 1: Natural language input.** A single text field with mic button
(same voice-compatible input used everywhere else in the UI). The user
describes what they want in plain language:

> "Review every file change for security issues and flag anything OWASP top 10"

**Step 2: LLM-assisted config generation.** The input is sent to a utility
sidecar completion that returns a best-guess `SidecarDefinition`:

```
POST /api/sidecars/generate
{ "description": "Review every file change for security issues..." }

→ {
    "name": "security-reviewer",
    "description": "Flag OWASP top 10 issues in file changes",
    "phase": "postflight",
    "lifetime": "ephemeral",
    "model": "claude-sonnet-4-20250514",
    "systemPrompt": "You are a security reviewer. Analyze the diff...",
    "triggers": [{ "condition": {"kind": "manual"}, ... }],
    ...
  }
```

The generation prompt includes the available context sources, trigger
conditions, output routes, and model list — everything the LLM needs to
produce a valid definition.

**Step 3: Form auto-population.** The generated config renders into a
detailed form with all fields visible and editable: name, description,
phase, lifetime, model selector, system prompt, trigger config, output
routing. Every field is pre-filled from the LLM output.

**Step 4: Confirm or tweak.** The user reviews, adjusts any field, and
saves. Saving writes to both the job (if pre-job) and the sidecar library
(for future reuse).

Every custom sidecar requires at minimum:

- **Name** — unique identifier, auto-generated from the description but
  editable
- **Description** — short human-readable summary, auto-generated from the
  natural language input, displayed in the sidecar library and job detail

The description doubles as the label shown in the UI sidecar list, the
metrics panel, and the job timeline.

### Sidecar library

Settings → Sidecars shows all saved templates. From here users can:

- Browse saved sidecars with name + description
- Edit any saved definition (opens the same form)
- Delete saved definitions
- Duplicate and modify
When creating a job, the advanced options section shows:

- A list of saved sidecars with checkboxes (none pre-checked)
- The natural language input field for creating a new one inline
- Each attached sidecar is expandable to show/edit its full config

## Wiring

### Startup (lifespan.py)

```python
dispatcher = SidecarDispatcher(session_manager, event_bus)

# RuntimeService registers its providers and callbacks
runtime_service.register_sidecar_providers(dispatcher)

# TrailService registers its providers and callbacks
trail_service.register_sidecar_providers(dispatcher)

# Subscribe dispatcher to event bus
event_bus.subscribe(dispatcher.handle_event)

# Start dispatcher tick loop
asyncio.create_task(dispatcher.tick_loop())
```

### Job start (RuntimeService.start_or_enqueue)

```python
# Resolve definitions: built-ins + custom from job spec
definitions = dispatcher.resolve_definitions(
    job=job,
    custom=job.sidecar_definitions or [],
)

# Activate: opens sessions, registers triggers
dispatcher.activate(job.id, definitions)
```

### Event flow

```
DomainEvent published
  → EventBus.publish() fans out to all subscribers
    → SidecarDispatcher.handle_event()
      → for each active sidecar with EventCondition matching this event:
        → _execute_pipeline(job_id, definition, pipeline, extra_context=event.payload)
    → TrailService.handle_event()
      → (trail node building, activity tracking — unchanged)
    → ...other subscribers
```

### Metric increments

Currently PlanManager counts tool calls and messages in `feed_transcript`.
Instead:

```python
# In TrailService._on_transcript_event():
if role in ("agent", "assistant"):
    dispatcher.increment(job_id, "messages")
if role == "tool_call":
    dispatcher.increment(job_id, "tool_calls")
```

The dispatcher evaluates threshold conditions on increment.

### Timer ticks

```python
# SidecarDispatcher.tick_loop():
async def tick_loop(self) -> None:
    while True:
        await asyncio.sleep(TICK_INTERVAL_S)
        await self.tick()
```

`tick()` iterates all active jobs and their timer-triggered sidecars,
checking if `interval_s` has elapsed since last fire (and optionally
`idle_guard_s` since last activity).

**Relationship to heartbeat loop:** The existing heartbeat loop in
RuntimeService publishes `session_heartbeat` events and tracks
`_last_activity`. The dispatcher's tick loop is separate — it only
evaluates timer conditions. The heartbeat loop stays for health reporting.
The stall check call (`await self._check_stall(job_id)`) is removed from
the heartbeat loop — the dispatcher handles it via the arbiter's timer
condition.

### Job completion

```python
# RuntimeService on terminal state:
await dispatcher.deactivate(job_id)
# deactivate() internally:
#   1. closes midflight sidecars (preserves metrics)
#   2. runs postflight sidecars
#   3. closes postflight sidecars
#   4. flushes all metrics to closed_jobs
```

## What changes, what doesn't

### Moves to the dispatcher

| Current location | What moves |
|---|---|
| `RuntimeService._check_stall()` | Prompt construction, LLM call, response parsing. Guard conditions move to `active_tool` context provider. Interrupt handling moves to `handle_stall_interrupt` callback. |
| `PlanManager._try_early_plan()` / `infer_plan()` | Prompt construction, LLM call, response parsing move to pipeline. Plan step creation moves to `apply_inferred_plan` callback. |
| `TrailService._maybe_auto_title()` | Entire method replaced by title_generator definition + `first_content` provider + `JobMetadataRoute`. |

### Stays in place

| Component | What stays | Why |
|---|---|---|
| `PlanManager.feed_native_plan()` | Native todo-tool parsing | Not an LLM call. Pure state management. |
| `PlanManager.feed_transcript()` | Message/tool buffering | State tracking, not sidecar work. Counter increments move to TrailService → `dispatcher.increment()`. |
| `PlanManager.finalize()` | Plan step finalization | Not an LLM call. |
| `TrailEnricher.drain_loop()` | Enrichment batching | Complex multi-job batching. Stays as background task calling `session_manager.complete()`. Not modeled as a sidecar definition. |
| `RuntimeService._heartbeat_loop()` | Health/heartbeat events | Not sidecar work. Stall check call removed. |
| `TrailService._on_transcript_event()` | Event routing | Simplified: removes plan-feed and title-gen inline calls, adds `dispatcher.increment()` for counters. |

### Enricher decision

The enricher is the odd one out. It operates across jobs, batches work, and
uses one-shot completions without a job-bound session. Forcing it into the
per-job sidecar model adds a `__global__` synthetic job_id hack.

**Decision: leave the enricher as-is.** It is a background task that happens
to use the LLM infrastructure. It is not a per-job sidecar. If a future
use case needs a "global sidecar" abstraction, add it then.

## Per-sidecar metrics

### Name-keyed tracking

`SidecarSessionManager` already tracks `(job_id → {name → SidecarSession})`
with per-session metrics. On `close_job()`, aggregate by name:

```python
{
    "arbiter": {"calls": 3, "costUsd": 0.002, "avgLatencyMs": 450},
    "planner": {"calls": 2, "costUsd": 0.003, "avgLatencyMs": 800},
}
```

### Dispatcher metrics

The dispatcher tracks per-sidecar-per-job:
- `trigger_count` — condition evaluated true
- `skip_count` — skipped (gate, concurrency, missing context)
- `error_count` — LLM call failed or parse failed
- `execute_count` — pipeline completed successfully

### API exposure

`GET /jobs/{id}/metrics` includes:

```json
{
  "sidecarSessions": {
    "arbiter": {
      "calls": 3,
      "costUsd": 0.002,
      "triggers": 5,
      "skips": 2,
      "errors": 0
    }
  }
}
```

## Migration path

### Step 1: SidecarDefinition + model selection

Add the type system: `SidecarDefinition`, `TriggerPipeline`,
`TriggerCondition` variants, `OutputParser`, `OutputRoute`. Add `model`
field threading through `SidecarSessionManager`. No behavioral changes.

### Step 2: SidecarDispatcher skeleton

Create the dispatcher with `activate()`, `deactivate()`, `handle_event()`,
`tick()`, `increment()`, `fire()`, `_execute_pipeline()`. Register it in
lifespan. Wire to EventBus. No triggers registered yet — dispatcher is
active but empty.

### Step 3: Migrate title generator

Easiest migration — self-contained, event-triggered, no complex state.
Define `BUILTIN_TITLE_GEN`, register `first_content` provider, remove
`TrailService._maybe_auto_title()`.

### Step 4: Migrate planner

Define `BUILTIN_PLANNER`, register `job_prompt` provider and
`apply_inferred_plan` callback. Move counter increments to
`dispatcher.increment()`. Remove `PlanManager._try_early_plan()` and
`infer_plan()` (the LLM-calling parts). Keep `feed_native_plan()`,
`feed_transcript()` (for buffering), `finalize()`.

### Step 5: Migrate arbiter

Define `BUILTIN_ARBITER`, register `active_tool` provider and
`handle_stall_interrupt` callback. Remove `_check_stall()` from
RuntimeService. Remove stall-related state (`_stall_check_pending`,
`_last_stall_check`). Keep heartbeat loop for health events.

### Step 6: Custom sidecars + postflight

Add `sidecars` field to `CreateJobRequest`. Implement `resolve_definitions()`
merge logic. Add `run_postflight()`. Add manual trigger API endpoint.

### Step 7: Per-sidecar metrics

Add name-keyed metric aggregation in `close_job()`. Add dispatcher metrics.
Expose in API.

### At each step

Tests. Run existing suite. Add tests for the new pipeline. Each step is
independently deployable — the old and new code paths don't coexist (each
migration removes the old path).
