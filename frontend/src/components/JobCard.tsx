import { memo } from "react";
import { useNavigate } from "react-router-dom";
import type { JobSummary } from "../store";
import { Badge } from "../ui/Badge";

function elapsed(createdAt: string): string {
  const ms = Date.now() - new Date(createdAt).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export const JobCard = memo(function JobCard({ job }: { job: JobSummary }) {
  const navigate = useNavigate();
  const repoName = job.repo.split("/").pop() ?? job.repo;

  return (
    <button
      className="w-full text-left bg-bg border border-border rounded-md p-3 mb-2 last:mb-0 cursor-pointer transition-colors hover:border-accent group"
      onClick={() => navigate(`/jobs/${job.id}`)}
    >
      <div className="flex justify-between items-center mb-1.5">
        <span className="font-semibold text-[13px] text-accent">{job.id.slice(0, 8)}</span>
        <Badge state={job.state} />
      </div>
      <div className="text-xs text-text-muted truncate mb-1" title={job.repo}>{repoName}</div>
      <div className="text-xs text-text line-clamp-2 leading-snug">{job.prompt}</div>
      <div className="flex justify-between items-center mt-2 text-[11px] text-text-dim">
        <span>{elapsed(job.createdAt)}</span>
        <span>{job.strategy}</span>
      </div>
    </button>
  );
});
