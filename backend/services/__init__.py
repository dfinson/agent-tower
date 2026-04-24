"""Business logic services.

Organisation
------------
Services are kept in a flat directory because the module count (~25) is
manageable and cross-cutting dependencies (e.g. EventBus used by both
DiffService and RuntimeService) make strict subdirectory grouping awkward.

Conceptual groups:

* **Agent adapters** — ``agent_adapter``, ``copilot_adapter``,
  ``claude_adapter``, ``adapter_registry``.
* **Job lifecycle** — ``job_service``, ``runtime_service``, ``merge_service``,
  ``diff_service``, ``approval_service``, ``permission_policy``.
* **Infrastructure** — ``event_bus``, ``sse_manager``, ``telemetry``,
  ``retention_service``, ``setup_service``.
* **Utilities** — ``git_service``, ``naming_service``, ``summarization_service``,
  ``utility_session``, ``tool_formatters``, ``voice_service``,
  ``terminal_service``, ``platform_adapter``.
"""

__all__ = [
    "adapter_registry",
    "agent_adapter",
    "approval_service",
    "artifact_service",
    "auth",
    "base_adapter",
    "claude_adapter",
    "conversation_ledger",
    "copilot_adapter",
    "cost_attribution",
    "diff_service",
    "event_bus",
    "git_service",
    "job_service",
    "lightweight_completer",
    "merge_service",
    "motivation_service",
    "naming_service",
    "permission_policy",
    "platform_adapter",
    "push_service",
    "retention_service",
    "retry_tracker",
    "runtime_service",
    "setup_service",
    "share_service",
    "sister_session",
    "sse_manager",
    "statistical_analysis",
    "step_persistence",
    "step_tracker",
    "story_service",
    "summarization_service",
    "telemetry",
    "terminal_service",
    "tool_classifier",
    "tool_formatters",
    "tunnel_service",
    "vapid_keys",
    "voice_service",
]
