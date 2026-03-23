# Configuration

CodePlane can be configured through environment variables, a global config file, and per-repository overrides.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CPL_TUNNEL_PASSWORD` | Password for Dev Tunnels remote access | _(none — tunnel has no auth)_ |

Set these in your `.env` file (copied from `.env.sample`).

## Global Configuration

CodePlane stores its configuration in `~/.codeplane/config.yaml`. This file is created on first run or via `cpl setup`.

Key configuration sections:

### Server

```yaml
server:
  host: 0.0.0.0
  port: 8080
```

### Agent Defaults

```yaml
agent:
  default_sdk: copilot          # copilot | claude
  default_model: ~              # model name, or ~ for SDK default
  permission_mode: auto         # auto | read_only | approval_required
```

### Permission Modes

| Mode | Behavior |
|------|----------|
| `auto` | Agent handles permissions automatically via SDK defaults |
| `read_only` | Agent can only read files; all writes require approval |
| `approval_required` | Every risky operation requires explicit operator approval |

### Retention

```yaml
retention:
  max_completed_jobs: 100       # max completed jobs to keep
  max_worktree_age_hours: 72    # auto-cleanup old worktrees
```

## Per-Repository Overrides

Place a `.codeplane.yml` file in any repository root to override global settings for that repo:

```yaml
# .codeplane.yml
agent:
  default_sdk: claude
  default_model: claude-sonnet-4-5
  permission_mode: approval_required
```

## UI Settings

Additional preferences can be configured from the **Settings** page (`Ctrl+,`):

<div class="screenshot-desktop" markdown>
![Settings Page](../images/screenshots/desktop/settings-page.png)
</div>

- **Registered repositories** — Add/remove repos
- **SDK selection** — Choose default SDK
- **Model preferences** — Set preferred model per SDK
