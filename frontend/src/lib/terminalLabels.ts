import type { JobSummary } from "../store";
import { pathBasename } from "./paths";

export function formatJobTerminalLabel(
  job: Pick<JobSummary, "repo" | "worktreeName" | "worktreePath" | "branch">,
  jobId: string,
): string {
  const repoName = pathBasename(job.repo) || "repo";
  const worktreeName = job.worktreeName || pathBasename(job.worktreePath) || job.branch || jobId;
  return `${repoName}:${worktreeName}`;
}