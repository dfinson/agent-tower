import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { FolderGit2, PlayCircle, Clock, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { fetchProjectsSummary } from "../api/client";
import type { ProjectSummaryResponse } from "../api/types";
import { Spinner } from "./ui/spinner";
import { pathBasename } from "../lib/paths";

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

function ProjectCard({ project, onOpen }: { project: ProjectSummaryResponse; onOpen: () => void }) {
  const hasJobs = project.activeJobCount > 0 || project.awaitingInputCount > 0 || project.failedCount > 0;
  const displayName = project.name || pathBasename(project.repoPaths[0] ?? "") || project.id;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="text-left rounded-lg border border-border bg-card p-4 space-y-3 hover:bg-accent/50 transition-colors"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold flex items-center gap-2 truncate">
          <FolderGit2 size={14} className="text-muted-foreground shrink-0" />
          <span className="truncate">{displayName}</span>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <PlayCircle size={12} className="text-blue-400" />
          {project.activeJobCount} active
        </span>
        <span className="flex items-center gap-1">
          <Clock size={12} className="text-yellow-400" />
          {project.awaitingInputCount} awaiting
        </span>
        <span className="flex items-center gap-1">
          <AlertTriangle size={12} className="text-red-400" />
          {project.failedCount} failed
        </span>
      </div>

      {!hasJobs && !project.lastActivityAt ? (
        <p className="text-xs text-muted-foreground/60">No jobs yet</p>
      ) : project.lastActivityAt ? (
        <p className="text-[10px] text-muted-foreground/60">Last activity {timeAgo(project.lastActivityAt)}</p>
      ) : null}
    </button>
  );
}

export function ProjectsOverview() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<ProjectSummaryResponse[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchProjectsSummary();
      setProjects(res.items);
    } catch {
      toast.error("Failed to load Projects overview");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openProject(project: ProjectSummaryResponse) {
    const firstRepo = project.repoPaths[0];
    if (!firstRepo) return;
    navigate(`/repos/${encodeURIComponent(firstRepo)}`);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="text-center">
          <FolderGit2 size={32} className="mx-auto mb-3 opacity-50" />
          <p className="text-sm">No Projects registered</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <h1 className="text-xl font-semibold text-foreground">Projects</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((project) => (
          <ProjectCard key={project.id} project={project} onOpen={() => openProject(project)} />
        ))}
      </div>
    </div>
  );
}
