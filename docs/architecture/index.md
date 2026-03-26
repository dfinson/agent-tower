# Architecture

CodePlane is intentionally split into a control-plane backend and a reactive browser UI. The design favors operator visibility, explicit state transitions, and thin integration boundaries over hidden orchestration.

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Operator Browser                      │
│              React + TypeScript Frontend                 │
│          REST (commands/queries) + SSE (live)            │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / SSE / WebSocket
┌────────────────────────▼─────────────────────────────────┐
│               FastAPI Backend (Python)                   │
│  REST API · SSE · Job orchestration · MCP server         │
│  Git service · Agent adapters · Approvals · Terminal     │
│  Voice transcription · Telemetry · Merge service         │
└────┬──────────┬──────────┬──────────┬──────────┬─────────┘
     │          │          │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼─────┐ ┌─▼──────┐ ┌─▼───────┐
│ SQLite │ │  Git   │ │Copilot  │ │ Claude │ │ Whisper │
│   DB   │ │  repos │ │  SDK    │ │  SDK   │ │ (local) │
└────────┘ └────────┘ └─────────┘ └────────┘ └─────────┘
```

## Key Design Principles

- **Thin API routes** — Route handlers validate input, delegate to services, return results
- **Repository pattern** — All database access through repository classes
- **Event-driven** — All runtime activity flows through domain events
- **Adapter pattern** — Agent SDKs wrapped behind a common interface
- **Single source of truth** — Pydantic schemas for API, Zustand store for UI state

## Deep Dives

| Section | Description |
|---------|-------------|
| [Backend](backend.md) | Services, repositories, event bus, and persistence |
| [Frontend](frontend.md) | Zustand store, SSE client, and component structure |
| [Agent Adapters](agent-adapters.md) | How Copilot and Claude SDKs are integrated |
| [Cloud-Native Design](cloud-native.md) | Future architecture for Kubernetes deployment |

## Design Notes

The architecture pages describe the system as it exists. Draft proposals and forward-looking design work live in the separate **Design Notes** section of the docs so implementation detail and exploration do not get conflated.
