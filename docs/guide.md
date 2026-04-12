---
hide:
  - navigation
---

# Usage Guide

## Creating Jobs

Jobs are the core unit of work. Each job runs an agent against a repository in an isolated Git worktree.

### Job Parameters

| Parameter | Description |
|-----------|-------------|
| **Prompt** | What you want the agent to do. Be specific — name files, describe the change, state constraints. |
| **Repository** | A registered local Git repo. Register repos in **Settings** (`Ctrl+,`). |
| **Agent** | GitHub Copilot CLI or Claude Code CLI. CodePlane manages the underlying SDKs — you just need the CLIs installed and authenticated. |
| **Model** | The AI model to use. Available models depend on your agent CLI and account. |

Press `Alt+N` or click **New Job** to open the form. Submit with **Create Job** or `Ctrl+Enter`.

### Voice Input

Click the microphone button to dictate your prompt. Audio is transcribed locally using [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — nothing leaves your machine.

---

## Monitoring Execution

Once a job starts, the detail view shows five tabs:

### Transcript

The primary monitoring view. Shows the agent's reasoning, tool calls (grouped with expandable details), operator messages you've sent, and AI-generated summaries of tool call groups.

Send messages to the agent at any time using the input box at the bottom. The agent receives your message as an operator instruction.

### Plan

The agent's planned steps with real-time status indicators for done, active, pending, and skipped steps.

### Logs

Structured log output with level filtering (debug, info, warning, error).

### Timeline

Visual timeline of execution phases — which are active, completed, or upcoming.

### Metrics

Token usage, estimated cost, LLM and tool call counts, cache hit rate, and context utilization.

### When to Intervene

- If the transcript shows repetitive actions, the agent may be stuck — send a message or cancel.
- If the plan isn't progressing, check logs for errors.
- If costs are climbing fast, check metrics to see if the agent is thrashing.

---

## Approvals

When an agent attempts a risky action, CodePlane can pause execution and ask for your approval.

### Permission Modes

| Mode | Behavior |
|------|----------|
| `full_auto` | Auto-approve all operations — reads, writes, shell commands, MCP tools, and URL fetches. No prompts. (default) |
| `review_and_approve` | Reads and read-only shell commands (grep, find, ls, cat) are auto-approved. Writes, mutating shell commands, URL fetches, and mutating MCP tools pause for your approval. |
| `observe_only` | Allow reads within the worktree and read-only shell commands. Block all writes, URL fetches, and mutations. |

Set the mode per-job in the creation form, per-repo in `.codeplane.yml`:

```yaml
permission_mode: review_and_approve
```

Or globally in `~/.codeplane/config.yaml`:

```yaml
runtime:
  permission_mode: review_and_approve
```

### Approval Actions

| Action | Effect |
|--------|--------|
| **Approve** | Allow this specific action |
| **Reject** | Block it — the agent may try an alternative |
| **Trust Session** | Auto-approve all remaining actions for this job |

### Hard-Gated Commands

Some commands **always** require approval regardless of mode: `git merge`, `git pull`, `git rebase`, `git cherry-pick`, and `git reset --hard`.

---

## Code Review

The **Diff** tab shows all files modified by the agent with syntax-highlighted, side-by-side diffs. Diffs update in real time as the agent works.

The **Workspace** view lets you browse the full file tree — not just changed files. This is useful for checking context or verifying overall structure.

---

## Merging & Resolution

When a job completes, it enters the **review** state. You decide how to land the changes:

| Option | Description |
|--------|-------------|
| **Merge** | Cherry-pick only the agent's meaningful commits onto the base branch, skipping setup noise |
| **Create PR** | Push the branch and open a pull request for team review |
| **Discard** | Delete the worktree and throw away all changes |

If a merge encounters conflicts, CodePlane shows the conflicting files. You can ask the agent to resolve them, discard, or create a PR instead.

After resolution, the job moves to `completed`. Archive it to move it to history and keep the dashboard clean.

### Resume with Instructions

From a job in the `review` state, send follow-up instructions to **resume the same job** — it transitions back to `running` in the same worktree with your new prompt. This lets you iterate on the agent's work without starting over.

---

## Remote & Mobile Access

CodePlane is built for remote supervision. Run the agent on your workstation, control it from your phone, tablet, or any device:

```bash
cpl up --remote                              # Dev Tunnels (default)
cpl up --remote --provider cloudflare        # Cloudflare Tunnels
cpl info                                     # show URL + QR code
```

The UI is fully responsive — optimized layouts for mobile, tablet, and desktop. From your phone you can:

- **Monitor** running jobs and live transcripts
- **Approve or reject** permission requests with one tap
- **Send messages** to steer an agent mid-run
- **Review diffs** in a mobile-optimized single-column view
- **Create new jobs** and browse history

Scan the QR code from `cpl info` to open CodePlane on your phone instantly.

Use `--phone` as a shortcut for `--remote` when you're primarily accessing from a mobile device:

```bash
cpl up --phone                               # same as --remote
```

### Push Notifications

Enable browser push notifications in **Settings → Notifications** to receive alerts even when the browser tab is in the background or closed:

- **Approval needed** — a job is waiting for your decision
- **Job completed** — the agent finished successfully
- **Job failed** — something went wrong

Notifications work on desktop browsers and on mobile when CodePlane is installed as a PWA (see below).

### Install as PWA

CodePlane serves a Progressive Web App manifest. On supported browsers (Chrome, Safari, Edge), you'll see an "Install" or "Add to Home Screen" option. The installed app:

- Launches full-screen without browser chrome
- Receives push notifications like a native app
- Caches static assets for faster loading

---

## Sharing Jobs

Share a read-only view of any job with a colleague or team member — no CodePlane password required.

1. Open a job's detail page
2. Click the **Share** button in the toolbar
3. A link is copied to your clipboard

The share link provides a minimal, non-interactive view showing the job's status, progress headline, and live logs via SSE. Share tokens expire after 24 hours.

Share viewers **cannot** approve actions, send messages, cancel jobs, or access the full workspace.

!!! note "Access scope"
    Share links bypass CodePlane's password but **not** the tunnel provider's identity gate. The viewer must already be able to reach the server (same tunnel, LAN, or localhost). Share links are designed for team members with tunnel access who shouldn't need the CodePlane password to view a job.

---

## Port Preview

If a job (or you via the terminal) starts a development server on a local port, you can access it remotely through the tunnel:

```
https://{tunnel-url}/api/preview/{port}/
```

For example, a Vite dev server on port 5173 would be accessible at `/api/preview/5173/`. Ports must be in the range 1024–65535.

---

## Additional Features

### Terminal

Press `` Ctrl+` `` to open the integrated terminal. Supports multiple tabs — global terminals or job-specific terminals rooted in the worktree.

### Command Palette

Press `⌘K` / `Ctrl+K` to search and navigate jobs by ID, title, repository, or branch.

### History

Archived jobs are browsable from the History page. Search, sort, and click into any past job to see its full transcript, diffs, and metrics.

### Analytics

Press `Alt+A` to open the analytics dashboard — aggregate costs, token usage, model breakdown, tool health, and per-repo spending across all jobs.

### MCP Server

CodePlane exposes an [MCP](https://modelcontextprotocol.io/) server at `http://localhost:8080/mcp`, enabling agent-to-agent orchestration. External agents can create and monitor jobs, handle approvals, browse worktrees, and manage repos programmatically — 7 tools in total.

CodePlane also discovers MCP servers (from `.vscode/mcp.json` or global config) and makes them available to the agent during job execution. See [Configuration > MCP Server Discovery](configuration.md#mcp-server-discovery) for setup details.

Full tool reference: [MCP Server](reference/mcp-server.md).

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Alt+N` | New job |
| `Alt+J` | Dashboard |
| `Alt+A` | Analytics |
| `⌘K` / `Ctrl+K` | Command palette |
| `⌘,` / `Ctrl+,` | Settings |
| `` Ctrl+` `` | Toggle terminal |
| `Ctrl+Enter` | Submit prompt / message |
| `/` | Filter jobs (dashboard) |
