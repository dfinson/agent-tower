"""Business logic services.

Organisation
------------
Services are organised into sub-packages by domain and flat modules for
cross-cutting or standalone concerns.

Sub-packages:

* **runtime/** — Job execution, queueing, heartbeat, resume, verify.
* **sidecar/** — Sidecar session management, dispatcher, templates.
* **watcher/** — Claude CLI and Copilot SDK session watchers.
* **setup/** — Preflight checks, dependency validation, setup wizard.
* **steps/** — Step tracking, diffing, persistence.
* **memory/** — Workspace memory compaction, extraction, read/write.
* **story/** — Story generation, review narrative, motivation.
* **trail/** — Activity timeline, plan tracking, enrichment.
* **action_policy/** — Permission evaluation, shell classification, batching.
* **merge_service/** — Git merge orchestration.

Flat modules:

* **Agent adapters** — ``agent_adapter``, ``base_adapter``,
  ``copilot_adapter/``, ``claude_adapter/``, ``adapter_registry``.
* **Telemetry & analytics** — ``telemetry``, ``telemetry_query_service``,
  ``cost_attribution``, ``analytics_service``, ``statistical_analysis``.
* **Infrastructure** — ``event_bus``, ``sse_manager``, ``push_service``,
  ``retention_service``.
* **Utilities** — ``git_service``, ``naming_service``, ``summarization_service``,
  ``tool_formatters/``, ``tool_classifier``, ``voice_service``,
  ``terminal_service``, ``tunnel_service``, ``platform_adapter``,
  ``parsing_utils``, ``snapshot_helpers``.
* **Auth & sharing** — ``auth``, ``cf_access``, ``share_service``,
  ``vapid_keys``.
* **Content** — ``artifact_service``, ``lightweight_completer``.
"""

__all__ = [
    "action_policy",
    "adapter_registry",
    "agent_adapter",
    "approval_service",
    "artifact_service",
    "auth",
    "base_adapter",
    "claude_adapter",
    "copilot_adapter",
    "cost_attribution",
    "diff_service",
    "event_bus",
    "git_service",
    "job_service",
    "lightweight_completer",
    "memory",
    "merge_service",
    "naming_service",
    "permission_policy",
    "platform_adapter",
    "push_service",
    "retention_service",
    "retry_tracker",
    "runtime",
    "setup",
    "share_service",
    "sidecar",
    "sse_manager",
    "statistical_analysis",
    "steps",
    "story",
    "summarization_service",
    "telemetry",
    "terminal_service",
    "tool_classifier",
    "tool_formatters",
    "trail",
    "tunnel_service",
    "vapid_keys",
    "voice_service",
    "watcher",
]
