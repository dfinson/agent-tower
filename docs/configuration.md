---
hide:
  - navigation
---

# Configuration

CodePlane works out of the box with sensible defaults. This page covers the settings you're most likely to change.

## First-Time Setup

Run the interactive setup wizard:

```bash
cpl setup
```

This walks you through registering a repository, selecting a default agent, and setting preferences.

## Global Config File

Location: `~/.codeplane/config.yaml` (created on first run or via `cpl setup`).

### Agent Defaults

```yaml
agent:
  default_sdk: copilot              # agent CLI to use: copilot | claude
  default_model: ~                  # model name, or ~ for agent default
  permission_mode: full_auto        # full_auto | observe_only | review_and_approve
```

| Permission Mode | Behavior |
|-----------------|---------|
| `full_auto` | All agent actions within the worktree are auto-approved — no prompts (default) |
| `observe_only` | Agent can read files and run safe commands (grep, ls, find); all writes and mutations are blocked |
| `review_and_approve` | Reads always allowed; file writes, shell commands (except grep/find), and network access pause for your approval |

### Server

```yaml
server:
  host: 0.0.0.0
  port: 8080
```

### Retention

```yaml
retention:
  max_completed_jobs: 100           # auto-cleanup oldest when exceeded
  max_worktree_age_hours: 72        # auto-delete old worktrees
```

## Per-Repository Overrides

Place a `.codeplane.yml` file in any repository root to override global settings for jobs in that repo:

```yaml
agent:
  default_sdk: claude
  default_model: claude-sonnet-4-5
  permission_mode: approval_required
```

## Remote Access

Run the agent on your workstation, control it from your phone or any browser. CodePlane supports two tunnel providers.

### Dev Tunnels (default)

**Prerequisite:** Install the [Dev Tunnels CLI](https://aka.ms/devtunnels/cli), or run `cpl setup` which handles it for you.

```bash
cpl up --remote                              # password auto-generated
cpl up --remote --password my-secret         # explicit password
cpl up --remote --tunnel-name my-tunnel      # reuse a named tunnel
```

A password is always required for remote access. By default one is auto-generated; set it explicitly via `--password` or the `CPL_PASSWORD` env var.

After startup, run `cpl info` to print the tunnel URL and a QR code you can scan from your phone.

### Cloudflare Tunnels

Use Cloudflare Tunnels when you want a stable public hostname (e.g., `codeplane.yourdomain.com`) instead of the auto-provisioned Dev Tunnels URL.

!!! danger "Cloudflare Access is required"
    Cloudflare Tunnels have no identity gate by default. CodePlane will **refuse to start** unless it detects a [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) application on the hostname.

**Prerequisites:**

1. Install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. [Create a named tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/) and route a public hostname to `http://localhost:8080`
3. [Create a Cloudflare Access application](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-app/) on that hostname with an identity policy. Email OTP is the simplest option; SSO and mTLS are also supported.

**Start CodePlane:**

```bash
export CPL_CLOUDFLARE_TUNNEL_TOKEN=eyJhIjo...      # from tunnel setup
export CPL_CLOUDFLARE_HOSTNAME=codeplane.yourdomain.com
cpl up --remote --provider cloudflare
```

At startup, CodePlane probes the hostname for a Cloudflare Access gate. If none is detected, the server exits with an error.

### All Remote Options

| CLI Flag | Env Var | Description |
|----------|---------|-------------|
| `--remote` | — | Enable remote access (required) |
| `--provider` | — | `devtunnel` (default) or `cloudflare` |
| `--password SECRET` | `CPL_PASSWORD` | Auth password (auto-generated if omitted) |
| `--tunnel-name NAME` | `CPL_DEVTUNNEL_NAME` | Reuse a named Dev Tunnel across restarts |
| — | `CPL_CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token |
| — | `CPL_CLOUDFLARE_HOSTNAME` | Cloudflare public hostname |

## Other Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_ENDPOINT` | OTLP endpoint for exporting metrics/traces | — (local only) |

## MCP Server Discovery

When a job starts, CodePlane discovers MCP servers to make available to the agent. Servers are merged from two sources (repo-level wins on name conflicts):

1. **Repo-level:** `.vscode/mcp.json` in the repository (VS Code / Copilot convention)
2. **Global:** `tools.mcp` in `~/.codeplane/config.yaml`

### Global config example

```yaml
tools:
  mcp:
    github:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
    postgres:
      command: uvx
      args: ["mcp-postgres"]
      env:
        DATABASE_URL: "${DATABASE_URL}"
```

### Repo-level example (`.vscode/mcp.json`)

```json
{
  "servers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

### Disabling servers per-repo

Add a `.codeplane.yml` file to the repository root:

```yaml
tools:
  mcp:
    disabled:
      - postgres
```

This prevents the `postgres` MCP server from starting for jobs in this repo, even if it's defined globally.

## UI Settings

Additional preferences are available in **Settings** (`Ctrl+,`): registered repositories, default agent, and model preferences.
