# MCP Server

CodePlane exposes an [MCP](https://modelcontextprotocol.io/) server that lets external agents orchestrate coding jobs, handle approvals, browse workspaces, and manage repositories programmatically.

**Endpoint:** `http://localhost:8080/mcp` (stateless HTTP transport via FastMCP)

## Tools

### `codeplane_job` — Manage Coding Jobs

| Action | Required Params | Optional Params | Description |
|--------|----------------|-----------------|-------------|
| `create` | `repo`, `prompt` | `base_ref`, `branch`, `model`, `sdk` | Create a new job |
| `list` | — | `state`, `limit` (default 50), `cursor` | List jobs with optional state filter |
| `get` | `job_id` | — | Get job details |
| `cancel` | `job_id` | — | Cancel a running job |
| `rerun` | `job_id` | — | Rerun a completed/failed job |
| `message` | `job_id`, `content` | — | Send a message to a running job (max 10,000 chars) |

### `codeplane_approval` — Manage Approvals

| Action | Required Params | Description |
|--------|----------------|-------------|
| `list` | `job_id` | List pending approvals for a job |
| `resolve` | `approval_id`, `resolution` | Approve or reject (`approved` / `rejected`) |

### `codeplane_workspace` — Browse Job Worktree

| Action | Required Params | Optional Params | Description |
|--------|----------------|-----------------|-------------|
| `list` | `job_id` | `path`, `cursor`, `limit` (max 200) | List directory contents |
| `read` | `job_id`, `path` | — | Read file contents (max 5 MB) |

Path validation enforces relative paths within the worktree — no `.git` access or `..` escapes.

### `codeplane_artifact` — Access Job Artifacts

| Action | Required Params | Description |
|--------|----------------|-------------|
| `list` | `job_id` | List artifacts for a job |
| `get` | `artifact_id` | Get artifact content |

### `codeplane_repo` — Manage Repositories

| Action | Required Params | Description |
|--------|----------------|-------------|
| `list` | — | List all registered repositories |
| `get` | `repo_path` | Get repository details (path, origin URL, base branch, platform) |
| `register` | `source` | Register a local path or remote Git URL (`clone_to` required for URLs) |
| `remove` | `repo_path` | Unregister a repository |

### `codeplane_settings` — Global Settings

| Action | Description |
|--------|-------------|
| `get` | Retrieve all settings |
| `update` | Update any combination of settings (see below) |

Updatable settings: `max_concurrent_jobs`, `permission_mode`, `auto_push`, `cleanup_worktree`, `delete_branch_after_merge`, `artifact_retention_days`, `max_artifact_size_mb`, `auto_archive_days`, `verify`, `self_review`, `max_turns`, `verify_prompt`, `self_review_prompt`.

### `codeplane_health` — Health & Maintenance

| Action | Description |
|--------|-------------|
| `check` | Returns status, version, uptime, active/queued job counts |
| `cleanup` | Remove worktrees for completed jobs |

## Example: Create and Monitor a Job

```json
// 1. Create a job
{"tool": "codeplane_job", "action": "create", "repo": "/repos/my-app", "prompt": "Add input validation to the signup endpoint"}

// 2. Check job status
{"tool": "codeplane_job", "action": "get", "job_id": "job-1"}

// 3. Approve a pending action
{"tool": "codeplane_approval", "action": "list", "job_id": "job-1"}
{"tool": "codeplane_approval", "action": "resolve", "approval_id": "abc-123", "resolution": "approved"}

// 4. Browse the result
{"tool": "codeplane_workspace", "action": "list", "job_id": "job-1"}
{"tool": "codeplane_workspace", "action": "read", "job_id": "job-1", "path": "src/signup.ts"}
```

## Authentication

The MCP endpoint uses the same authentication as the web UI. When remote access is enabled (`--remote`), requests must include the tunnel password cookie.

## Disabling

The MCP server is enabled by default. It cannot be disabled globally, but individual MCP tools that CodePlane's agents use during job execution can be disabled per-repo — see [MCP Server Discovery](../configuration.md#mcp-server-discovery).
