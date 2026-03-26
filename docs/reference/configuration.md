# Configuration Reference

CodePlane is configured through environment variables, a global YAML config file, and per-repository overrides.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CPL_DEVTUNNEL_PASSWORD` | Password for Dev Tunnels remote access | _(auto-generated with --remote)_ |
| `CPL_DEVTUNNEL_NAME` | Dev Tunnel name (reused across restarts) | _(random)_ |
| `CPL_CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token | _(none)_ |
| `CPL_CLOUDFLARE_HOSTNAME` | Cloudflare public hostname | _(none)_ |
| `OTEL_EXPORTER_ENDPOINT` | OTLP exporter endpoint for metrics/traces | _(none — local only)_ |

## Global Config File

Location: `~/.codeplane/config.yaml`

Created on first run or via `cpl setup`.

### Server

```yaml
server:
  host: 0.0.0.0        # bind address
  port: 8080            # listen port
```

### Agent

```yaml
agent:
  default_sdk: copilot          # copilot | claude
  default_model: ~              # model name, or ~ for SDK default
  permission_mode: auto         # auto | read_only | approval_required
  max_turns: ~                  # max agent turns per session (~ = unlimited)
```

### Tunnel

```yaml
tunnel:
  enabled: false                # auto-enabled by --remote flag
  password: ~                   # overridden by CPL_DEVTUNNEL_PASSWORD
```

### Retention

```yaml
retention:
  max_completed_jobs: 100       # max completed jobs before cleanup
  max_worktree_age_hours: 72    # auto-delete old worktrees
```

### Observability

```yaml
observability:
  log_level: info               # debug | info | warning | error
  structured_logging: true      # JSON log format
```

### Heartbeat

```yaml
heartbeat:
  interval_seconds: 30          # emit heartbeat every N seconds
  warn_after_seconds: 90        # warn if no heartbeat for N seconds
  fail_after_seconds: 300       # fail job if no heartbeat for N seconds
```

### Tunnel

```yaml
tunnel:
  provider: devtunnel      # devtunnel | cloudflare
  password: ~              # overridden by CPL_DEVTUNNEL_PASSWORD or --password
```

### OTEL Export

```yaml
# Optional: push metrics/traces to an external collector
# Set OTEL_EXPORTER_ENDPOINT env var to enable
```

## Per-Repository Overrides

Place a `.codeplane.yml` file in any repository root:

```yaml
# .codeplane.yml
agent:
  default_sdk: claude
  default_model: claude-sonnet-4-5
  permission_mode: approval_required
```

Per-repo settings override the global config for jobs running against that repository.

## MCP Discovery

External agents discover CodePlane's MCP server at:

```
http://localhost:8080/mcp
```

The MCP server uses HTTP transport and is enabled by default.
