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
