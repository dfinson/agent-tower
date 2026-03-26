# Creating Jobs

Jobs are the core unit of work in CodePlane. Each job runs a coding agent against a repository in an isolated Git worktree.

## Opening the Job Form

- Press `Alt+N` from anywhere in the UI
- Or click the **+ New Job** button in the header

## Job Parameters

### Prompt

Write a clear description of the coding task. Be specific about what you want:

!!! tip "Good Prompts"
    - "Add input validation to the user registration endpoint in `src/api/users.py`. Validate email format and password strength."
    - "Refactor the `OrderService` class to use the repository pattern instead of direct database queries."

!!! warning "Avoid Vague Prompts"
    - "Fix the code" — too vague
    - "Make it better" — no actionable direction

### Repository

Select a registered repository from the dropdown. If you haven't registered one yet, go to **Settings** (`Ctrl+,`) first.

### SDK

Choose the agent SDK to use:

- **GitHub Copilot** — Broad model selection, works with any Copilot-available model
- **Claude Code** — Anthropic's Claude models (claude-* family)

### Model

Select a specific model within the chosen SDK. The available models depend on your SDK selection and account access.

## Voice Input

Click the **microphone button** to dictate your prompt instead of typing:

1. Click the mic button — it turns red while recording
2. Speak your prompt naturally
3. The audio is transcribed locally using Whisper — nothing leaves your machine
4. The transcription appears in the prompt textarea for editing
5. Press `Ctrl+Enter` to submit

## Submitting

Click **Create Job** or press `Ctrl+Enter`. The job enters the **queued** state and begins execution.

<div class="screenshot-desktop" markdown>
![Job Creation Filled](../images/screenshots/desktop/job-creation-filled.png)
</div>

## What Happens Next

1. CodePlane creates an isolated **Git worktree** for the job
2. The agent SDK session starts with your prompt
3. The job appears on the dashboard and starts streaming updates
4. You can [monitor execution](monitoring-jobs.md) in real time
