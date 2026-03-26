# Terminal

CodePlane includes an integrated terminal powered by xterm.js, giving you shell access alongside the agent.

## Opening the Terminal

Press `` Ctrl+` `` to toggle the terminal drawer, or click the terminal icon in the header.

<div class="screenshot-desktop" markdown>
![Terminal Drawer](../images/screenshots/desktop/terminal-drawer.png)
</div>

## Features

### Multi-Tab Support

Create multiple terminal sessions with the **+** button. Each session runs independently:

- **Global terminals** — Not tied to any job
- **Job terminals** — Opened from a job's context, with the working directory set to the job's worktree

### Resizable Drawer

Drag the top edge of the terminal drawer to resize it. On mobile, the drawer automatically maximizes to 90% of the viewport height.

<div class="screenshot-mobile" markdown>
![Mobile Terminal](../images/screenshots/mobile/mobile-terminal.png)
</div>

### Tab Management

- Click a tab to switch sessions
- Close tabs with the × button
- Tabs auto-number sequentially (Terminal 1, Terminal 2, etc.)

## Use Cases

- **Inspect the workspace** — `ls`, `cat`, `git log` in the job's worktree
- **Debug issues** — Run tests or check error output while the agent works
- **Manual fixes** — Make small corrections alongside the agent
- **Git operations** — Check branch state, resolve conflicts, push changes
