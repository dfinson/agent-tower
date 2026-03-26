# MCP Server

CodePlane exposes an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, allowing external AI agents to orchestrate CodePlane jobs programmatically.

## What Is MCP?

MCP is a protocol that lets AI agents discover and use tools exposed by other systems. CodePlane's MCP server turns every CodePlane operation into a tool that external agents can call.

## Available Tools

CodePlane exposes 7 tool groups:

| Tool | Actions | Description |
|------|---------|-------------|
| `codeplane_job` | create, list, get, cancel, rerun, send_message | Manage coding jobs |
| `codeplane_approval` | list, approve, reject, trust | Handle approval requests |
| `codeplane_workspace` | list_files, read_file | Browse job workspaces |
| `codeplane_artifact` | list, get | Access job artifacts |
| `codeplane_settings` | get, update | Read/write settings |
| `codeplane_repo` | list, register, unregister | Manage repositories |
| `codeplane_health` | check | Health check |

Each tool multiplexes several actions via an `action` parameter.

## Use Cases

### Agent-to-Agent Orchestration

An outer agent (e.g., a project manager agent) can:

1. Create a CodePlane job with a specific prompt
2. Monitor its progress
3. Handle approvals automatically
4. Review the results
5. Create additional follow-up jobs

### CI/CD Integration

Use MCP tools from CI pipelines or automation scripts to:

- Launch coding tasks on pull request events
- Auto-approve certain categories of operations
- Collect artifacts and metrics

## Connecting

The MCP server runs on the same port as the main API. Configure your MCP client to connect to:

```
http://localhost:8080/mcp
```

The server supports HTTP transport with SSE notifications for real-time updates.

## Tool Annotations

Each tool action is annotated with metadata:

- **Destructive** — Whether the action modifies state
- **Read-only** — Whether the action only reads data
- **Idempotent** — Whether repeated calls have the same effect

This helps MCP clients make informed decisions about tool safety.
