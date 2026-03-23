# Agent Adapters

CodePlane supports multiple AI coding agent SDKs through an adapter pattern. Each SDK is wrapped behind a common interface, isolating SDK-specific code from the rest of the system.

## Architecture

```
RuntimeService
    │
    ▼
AdapterRegistry
    │
    ├── CopilotAdapter (GitHub Copilot SDK)
    └── ClaudeAdapter (Claude Code SDK)
```

## AgentAdapterInterface

All adapters implement the `AgentAdapterInterface` abstract base class:

```python
class AgentAdapterInterface(ABC):
    @abstractmethod
    async def create_session(self, config: SessionConfig) -> str: ...

    @abstractmethod
    async def stream_events(self, session_id: str) -> AsyncIterator[SessionEvent]: ...

    @abstractmethod
    async def send_message(self, session_id: str, message: str) -> None: ...

    @abstractmethod
    async def abort_session(self, session_id: str) -> None: ...
```

## Key Rules

1. **Never import SDK types outside the adapter** — All SDK-specific types and imports are contained within the adapter file
2. **Adapters are stateless wrappers** — They translate between CodePlane's domain and the SDK's API
3. **N + M, not N × M** — Adding a new SDK = one new adapter. Adding a new execution backend = one new backend. They compose independently.

## Copilot Adapter

`backend/services/copilot_adapter.py`

- Uses the GitHub Copilot SDK
- Supports any model available through the Copilot platform
- Handles permission callbacks via CodePlane's approval system

## Claude Adapter

`backend/services/claude_adapter.py`

- Uses the Claude Code SDK
- Supports `claude-*` model family only
- Validates model names on session creation

## Adapter Registry

`backend/services/adapter_registry.py`

The registry maps SDK names to adapter instances:

```python
registry = AdapterRegistry()
adapter = registry.get("copilot")  # Returns CopilotAdapter
adapter = registry.get("claude")   # Returns ClaudeAdapter
```

## Adding a New SDK

To add support for a new coding agent SDK:

1. Create `backend/services/new_adapter.py` implementing `AgentAdapterInterface`
2. Register it in `AdapterRegistry`
3. Add the SDK name to the allowed values in API schemas
4. No other code changes needed — the adapter pattern handles the rest
