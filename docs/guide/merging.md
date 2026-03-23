# Merging

When a job completes successfully, you choose how to handle the agent's changes.

## Resolution Options

Click the **Complete** button on a succeeded job to open the resolution dialog:

<div class="screenshot-desktop" markdown>
![Complete Job Dialog](../images/screenshots/desktop/complete-job-dialog.png)
</div>

<div class="screenshot-mobile" markdown>
![Mobile Complete Dialog](../images/screenshots/mobile/mobile-complete-dialog.png)
</div>

| Option | Description |
|--------|-------------|
| **Merge** | Merge the worktree branch into the base branch |
| **Smart Merge** | Cherry-pick only the agent's commits (skips setup commits) |
| **Create PR** | Create a pull request for team review |
| **Discard** | Delete the worktree and discard all changes |
| **Agent Merge** | Let the agent handle the merge process |

## Merge vs. Smart Merge

- **Merge** performs a standard Git merge of the entire worktree branch
- **Smart Merge** uses cherry-pick to apply only the meaningful commits, skipping any setup or initialization commits

Smart merge is useful when the worktree branch has diverged significantly from the base.

## Pull Request Creation

Choosing **Create PR** will:

1. Push the worktree branch to the remote
2. Create a pull request via the platform API (GitHub, Azure DevOps, or GitLab)
3. Display the PR URL in the UI

## Conflict Handling

If a merge encounters conflicts, CodePlane detects them and displays the conflicting files. You can then:

- Resolve conflicts manually in the terminal
- Discard and try a different merge strategy
- Create a PR instead for manual resolution

## After Resolution

Once resolved, the job moves to the `resolved` state. You can then **archive** it to move it to history, keeping the dashboard clean.
