import { useEffect, useState } from "react";
import { useParams, Link, Navigate } from "react-router-dom";
import {
  GitBranch, Globe, Activity, DollarSign, Boxes,
  AlertTriangle, Briefcase, LayoutGrid,
} from "lucide-react";
import { toast } from "sonner";
import { fetchRepoSummary, fetchProject } from "../api/client";
import type { RepoSummaryResponse } from "../api/client";
import type { ProjectResponse } from "../api/types";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";
import { pathBasename } from "../lib/paths";

function StatBadge({ icon: Icon, label, value, className }: {
  icon: React.ComponentType<{ size?: string | number; className?: string }>;
  label: string;
  value: string | number;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", className)}>
      <Icon size={12} className="shrink-0" />
      <span>{label}:</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

function stateColor(state: string): string {
  switch (state) {
    case "running":
    case "preparing":
      return "text-blue-400";
    case "completed":
      return "text-green-400";
    case "failed":
    case "error":
      return "text-red-400";
    case "paused":
      return "text-yellow-400";
    default:
      return "text-muted-foreground";
  }
}

function formatCost(usd: number | null | undefined): string {
  if (usd == null || usd === 0) return "$0";
  if (usd < 0.01) return "<$0.01";
  return `$${usd.toFixed(2)}`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/**
 * Project overview, keyed by stable `project.id` (not `repoPaths[0]`) so the
 * URL survives a Project's member-repo edits and is safe to bookmark/share.
 * The underlying repo-summary card still reflects one representative repo
 * (the Project's first member) — genuinely multi-repo aggregation for this
 * card is a larger follow-up; the Board already aggregates across all
 * member repos (`selectActiveJobsForProject` etc).
 */
export function RepoOverview() {
  const { projectId } = useParams<{ projectId: string }>();

  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<RepoSummaryResponse | null>(null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [error, setError] = useState(false);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let ignore = false;
    setLoading(true);
    setError(false);
    setNotFound(false);
    fetchProject(projectId)
      .then((proj) => {
        if (ignore) return;
        setProject(proj);
        const repoPath = proj.repoPaths[0];
        if (!repoPath) {
          setLoading(false);
          return;
        }
        fetchRepoSummary(repoPath)
          .then((res) => { if (!ignore) setSummary(res); })
          .catch(() => { if (!ignore) { setError(true); toast.error("Failed to load repository summary"); } })
          .finally(() => { if (!ignore) setLoading(false); });
      })
      .catch((err: unknown) => {
        if (ignore) return;
        const status = (err as { status?: number } | null)?.status;
        if (status === 404) {
          setNotFound(true);
        } else {
          setError(true);
          toast.error("Failed to load Project");
        }
        setLoading(false);
      });
    return () => { ignore = true; };
  }, [projectId]);

  if (notFound) {
    return <Navigate to="/projects" replace />;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <p>{error ? "Failed to load Project" : "Project not found"}</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {/* Header */}
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-xl font-semibold text-foreground">{project.name}</h1>
          <p className="text-xs text-muted-foreground">{project.repoPaths.length} member repositories</p>
          <Link
            to={`/projects/id/${encodeURIComponent(project.id)}/board`}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors shrink-0"
          >
            <LayoutGrid size={12} />
            Board
          </Link>
        </div>
        {summary && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            {summary.originUrl && (
              <span className="flex items-center gap-1">
                <Globe size={12} />
                <span className="truncate max-w-[20rem]">{summary.originUrl}</span>
              </span>
            )}
            {summary.currentBranch && (
              <span className="flex items-center gap-1">
                <GitBranch size={12} />
                {summary.currentBranch}
              </span>
            )}
            {summary.activeJobCount > 0 && (
              <span className="flex items-center gap-1 text-blue-400">
                <Activity size={12} />
                {summary.activeJobCount} active
              </span>
            )}
            {summary.platform && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] uppercase tracking-wider">
                {summary.platform}
              </span>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-1.5 pt-2">
          {project.repoPaths.map((path) => (
            <span key={path} className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-mono">{pathBasename(path) || path}</span>
          ))}
        </div>
      </div>

      {!summary ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground text-sm">
          No member repository available for this Project yet.
        </div>
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Recent Jobs */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold flex items-center gap-2">
              <Briefcase size={14} className="text-muted-foreground" />
              Recent Jobs
            </span>
            <Link
              to={`/projects/id/${encodeURIComponent(project.id)}/repos/${encodeURIComponent(project.repoPaths[0] ?? "")}/jobs`}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              View all →
            </Link>
          </div>
          {summary.recentJobs.length === 0 ? (
            <p className="text-xs text-muted-foreground py-3 text-center">No jobs yet</p>
          ) : (
            <div className="space-y-1">
              {summary.recentJobs.map((job) => (
                <Link
                  key={job.id}
                  to={`/jobs/${job.id}`}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-accent transition-colors group"
                >
                  <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", {
                    "bg-blue-400": job.state === "running" || job.state === "preparing",
                    "bg-green-400": job.state === "completed",
                    "bg-red-400": job.state === "failed" || job.state === "error",
                    "bg-yellow-400": job.state === "paused",
                    "bg-muted-foreground": !["running", "preparing", "completed", "failed", "error", "paused"].includes(job.state),
                  })} />
                  <span className="flex-1 text-xs truncate text-foreground/90">
                    {job.title || job.id.slice(0, 8)}
                  </span>
                  <span className={cn("text-[10px]", stateColor(job.state))}>
                    {job.state}
                  </span>
                  {job.totalCostUsd != null && job.totalCostUsd > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      {formatCost(job.totalCostUsd)}
                    </span>
                  )}
                  <span className="text-[10px] text-muted-foreground/60">
                    {timeAgo(job.createdAt)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Cost */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold flex items-center gap-2">
              <DollarSign size={14} className="text-muted-foreground" />
              Cost (7d)
            </span>
            <Link
              to={`/projects/id/${encodeURIComponent(project.id)}/repos/${encodeURIComponent(project.repoPaths[0] ?? "")}/cost`}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Details →
            </Link>
          </div>
          <div className="space-y-2">
            <div className="text-2xl font-bold text-foreground">
              {formatCost(summary.cost.totalCostUsd)}
            </div>
            <div className="flex items-center gap-4">
              <StatBadge icon={Briefcase} label="Jobs" value={summary.cost.totalJobs} />
              <StatBadge icon={Activity} label="Tokens" value={summary.cost.totalTokens.toLocaleString()} />
            </div>
          </div>
        </div>

        {/* Structural Health */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-semibold flex items-center gap-2">
              <Boxes size={14} className="text-muted-foreground" />
              Structural Health
            </span>
            <Link
              to={`/projects/id/${encodeURIComponent(project.id)}/repos/${encodeURIComponent(project.repoPaths[0] ?? "")}/health`}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              Details →
            </Link>
          </div>
          {!summary.health ? (
            <p className="text-xs text-muted-foreground py-3 text-center">
              CodeRecon not available
            </p>
          ) : summary.health.indexStatus === "error" ? (
            <p className="text-xs text-red-400 py-3 text-center flex items-center justify-center gap-1.5">
              <AlertTriangle size={12} />
              Index error
            </p>
          ) : (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <StatBadge icon={Boxes} label="Symbols" value={summary.health.symbolCount.toLocaleString()} />
                <StatBadge icon={Boxes} label="Files" value={summary.health.fileCount.toLocaleString()} />
                <StatBadge icon={Boxes} label="Communities" value={summary.health.communityCount} />
                <StatBadge
                  icon={AlertTriangle}
                  label="Cycles"
                  value={summary.health.cycleCount}
                  className={summary.health.cycleCount > 0 ? "text-yellow-400" : undefined}
                />
              </div>
              {summary.health.lastIndexedSha && (
                <p className="text-[10px] text-muted-foreground/60">
                  Last indexed: {summary.health.lastIndexedSha.slice(0, 7)}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
