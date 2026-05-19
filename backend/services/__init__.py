"""Business logic services.

Organisation
------------
All services are organised into sub-packages by domain concern.

Sub-packages:

* **action_policy/** — Permission evaluation, shell classification, batching.
* **adapters/** — Agent adapter abstraction layer, SDK event mapping.
* **analytics/** — Cost attribution, latency, telemetry, statistical analysis.
* **artifacts/** — Artifact storage, diffs, and snapshot helpers.
* **auth/** — Authentication middleware, Cloudflare Access, permission policy.
* **claude_adapter/** — Claude CLI adapter.
* **coderecon/** — CodeRecon integration services.
* **completers/** — LLM completion, summarization, naming, narration, voice.
* **copilot_adapter/** — Copilot SDK adapter.
* **events/** — Event bus, SSE, event processing pipeline.
* **git/** — Git operations service.
* **job/** — Job lifecycle, approval, retry, retention.
* **merge_service/** — Git merge orchestration.
* **runtime/** — Job execution, queueing, heartbeat, resume, verify.
* **setup/** — Preflight checks, dependency validation, setup wizard.
* **sharing/** — Sharing, tunnels, push notifications, VAPID keys.
* **sidecar/** — Sidecar session management, dispatcher, templates.
* **steps/** — Step tracking, diffing, persistence.
* **story/** — Story generation, review narrative, motivation.
* **terminal/** — PTY-based terminal session management.
* **tool_formatters/** — Tool display formatting and visibility.
* **tools/** — Tool classification, preflight curation, parsing utilities.
* **trail/** — Activity timeline, plan tracking, enrichment.
* **watcher/** — Claude CLI and Copilot SDK session watchers.
"""

__all__ = [
    "action_policy",
    "adapters",
    "analytics",
    "artifacts",
    "auth",
    "claude_adapter",
    "coderecon",
    "completers",
    "copilot_adapter",
    "events",
    "git",
    "job",
    "memory",
    "merge_service",
    "runtime",
    "setup",
    "sharing",
    "sidecar",
    "steps",
    "story",
    "terminal",
    "tool_formatters",
    "tools",
    "trail",
    "watcher",
]
