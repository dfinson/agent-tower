# Monitoring Jobs

CodePlane provides real-time visibility into every aspect of agent execution through multiple monitoring views.

## Dashboard

The main dashboard shows all active jobs in a Kanban-style board with three columns:

- **In Progress** — Currently executing jobs
- **Awaiting Input** — Jobs waiting for operator approval
- **Failed** — Jobs that encountered errors

<div class="screenshot-desktop" markdown>
![Dashboard](../images/screenshots/desktop/hero-dashboard.png)
</div>

On mobile, the dashboard switches to a tab-based list view:

<div class="screenshot-mobile" markdown>
![Mobile Dashboard](../images/screenshots/mobile/mobile-dashboard.png)
</div>

### Search & Filter

Use the search bar or press `/` to filter jobs by ID, title, repository, branch, or prompt content.

<div class="screenshot-mobile" markdown>
![Mobile Search](../images/screenshots/mobile/mobile-dashboard-search.png)
</div>

### Sort Options

Sort jobs by: newest, oldest, recently updated, or alphabetical.

## Job Detail View

Click any job card to open the detail view. It contains several tabs:

### Transcript

The primary monitoring view. Shows the agent's conversation as a chat-like interface:

- **Assistant messages** — The agent's reasoning and responses (rendered as Markdown)
- **Tool call groups** — Grouped tool invocations with name, arguments, result, and success/failure status
- **AI summaries** — Auto-generated summaries of related tool call groups
- **Operator messages** — Messages you've sent to the agent
- **Progress headlines** — Short status updates (e.g., "Analyzing codebase...")

<div class="screenshot-desktop" markdown>
![Transcript](../images/screenshots/desktop/job-running-transcript.png)
</div>

<div class="screenshot-mobile" markdown>
![Mobile Transcript](../images/screenshots/mobile/mobile-job-transcript.png)
</div>

You can send messages to the agent at any time using the input box at the bottom of the transcript. The agent receives your message as an operator instruction.

### Logs

Structured log output with level filtering:

- **Debug** — Detailed internal operations
- **Info** — Normal operation messages
- **Warning** — Potential issues
- **Error** — Failures and exceptions

Use the level dropdown to filter by severity.

<div class="screenshot-desktop" markdown>
![Logs](../images/screenshots/desktop/job-running-logs.png)
</div>

### Timeline

Visual timeline showing the agent's progress through execution phases:

- Active phases are highlighted
- Completed phases show duration
- Future phases are dimmed

<div class="screenshot-desktop" markdown>
![Timeline](../images/screenshots/desktop/job-running-timeline.png)
</div>

### Plan

The agent's planned steps with real-time status tracking:

- ✅ **Done** — Completed steps
- 🔄 **Active** — Currently executing
- ⏳ **Pending** — Not yet started
- ⏭️ **Skipped** — Agent decided to skip

<div class="screenshot-desktop" markdown>
![Plan](../images/screenshots/desktop/job-running-plan.png)
</div>

### Metrics

Token usage and cost tracking per job:

- **Input/Output tokens** — With cache hit breakdown
- **Total cost** — Estimated cost for the job
- **LLM calls** — Number of API calls made
- **Tool calls** — Number of tools invoked
- **Context utilization** — How much of the context window is being used

<div class="screenshot-desktop" markdown>
![Metrics](../images/screenshots/desktop/job-running-metrics.png)
</div>

## Job States

Jobs go through several states during their lifecycle. See [Job States Reference](../reference/job-states.md) for the complete state machine.

<div class="screenshot-desktop" markdown>
![Succeeded Job](../images/screenshots/desktop/job-succeeded.png)
</div>

<div class="screenshot-desktop" markdown>
![Failed Job](../images/screenshots/desktop/job-failed.png)
</div>

## Operator Actions

While a job is running, you can:

- **Send a message** — Type instructions in the transcript input
- **Cancel** — Stop the job immediately
- **Pause** — Pause execution (resume later with optional new instructions)
