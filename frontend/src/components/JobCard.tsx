import { memo } from "react";
import { useNavigate } from "react-router-dom";
import type { JobSummary } from "../store";
import { StateBadge } from "./StateBadge";

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
    <div
      className="job-card"
      onClick={() => navigate(`/jobs/${job.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") navigate(`/jobs/${job.id}`);
      }}
    >
      <div className="job-card__header">
        <span className="job-card__id">{job.id.slice(0, 8)}</span>
        <StateBadge state={job.state} />
      </div>
      <div className="job-card__repo">{repoName}</div>
      <div className="job-card__prompt">{job.prompt}</div>
      <div className="job-card__footer">
        <span>{elapsed(job.createdAt)}</span>
        <span>{job.strategy}</span>
      </div>
    </div>
  );
});
