# History

CodePlane lets you archive completed jobs and browse them later.

## Archiving Jobs

After a job is resolved (merged, PR created, or discarded), click **Archive** to move it to history. This keeps the main dashboard clean while preserving the full job record.

## Browsing History

Navigate to the **History** page from the main navigation:

<div class="screenshot-desktop" markdown>
![History Page](../images/screenshots/desktop/history-page.png)
</div>

- **Search** — Filter archived jobs by title, ID, repo, or branch
- **Sort** — Order by date, name, or status
- **View details** — Click any archived job to see its full transcript, logs, diffs, and metrics

## Restoring Jobs

Click **Unarchive** on any archived job to restore it to the main dashboard. The job retains all its data — transcript, diffs, logs, and metrics.

## Follow-Up Jobs

From any job in the `review` state, you can create a **follow-up job** that continues in the same worktree with a new instruction. This lets you iterate on the agent's work without starting from scratch.

## Retention

Archived jobs are kept according to your retention settings:

```yaml
# ~/.codeplane/config.yaml
retention:
  max_completed_jobs: 100
```

When the limit is reached, the oldest archived jobs are automatically cleaned up.
