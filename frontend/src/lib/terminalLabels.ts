import type { JobSummary } from "../store";

function pathLeaf(path: string | null | undefined): string | null {
  if (!path) return null;
  const parts = path.split("/").filter(Boolean);
  return parts.length > 0 ? (parts[parts.length - 1] ?? null) : null;
}

export function formatJobTerminalLabel(
  job: Pick<JobSummary, "repo" | "worktreeName" | "worktreePath" | "branch">,
  jobId: string,
): string {
  const repoName = pathLeaf(job.repo) ?? "repo";
  const worktreeName = job.worktreeName ?? pathLeaf(job.worktreePath) ?? job.branch ?? jobId;
  return `${repoName}:${worktreeName}`;
}