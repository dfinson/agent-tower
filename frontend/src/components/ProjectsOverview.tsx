import { useEffect, useState, useCallback, useMemo } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { FolderGit2, PlayCircle, Clock, AlertTriangle, Plus } from "lucide-react";
import { toast } from "sonner";
import { fetchProjectsSummary } from "../api/client";
import type { ProjectSummaryResponse } from "../api/types";
import { Spinner } from "./ui/spinner";
import { Button } from "./ui/button";
import { pathBasename } from "../lib/paths";
import { matchesNameFilter } from "../lib/nameFilter";
import { CreateProjectDialog } from "./CreateProjectDialog";
import type { RepoLayoutOutletContext } from "./RepoLayout";

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

function projectDisplayName(project: ProjectSummaryResponse): string {
  return project.name || pathBasename(project.repoPaths[0] ?? "") || project.id;
}

function ProjectCard({ project, onOpen }: { project: ProjectSummaryResponse; onOpen: () => void }) {
  const hasJobs = project.activeJobCount > 0 || project.awaitingInputCount > 0 || project.failedCount > 0;
  const displayName = projectDisplayName(project);

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
  const layoutContext = useOutletContext<RepoLayoutOutletContext | null>();
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<ProjectSummaryResponse[]>([]);
  const [filterQuery, setFilterQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  // Combined cross-Project attention signal (Story 2.4): summed awaiting+failed
  // across all Projects, derived from the same batch summary fetch as Story 2.2
  // (no second endpoint, no extra fetch).
  const attentionCount = useMemo(
    () => projects.reduce((sum, p) => sum + p.awaitingInputCount + p.failedCount, 0),
    [projects],
  );

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
    navigate(`/projects/id/${encodeURIComponent(project.id)}/board`);
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
        <div className="text-center space-y-3">
          <FolderGit2 size={32} className="mx-auto opacity-50" />
          <p className="text-sm">No Projects registered</p>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus size={14} />
            New Project
          </Button>
        </div>
        <CreateProjectDialog
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={(project) => {
            layoutContext?.onProjectCreated(project);
            setProjects((current) => [...current, {
              ...project,
              activeJobCount: 0,
              awaitingInputCount: 0,
              failedCount: 0,
              lastActivityAt: null,
            }]);
            navigate(`/projects/id/${encodeURIComponent(project.id)}`);
          }}
        />
      </div>
    );
  }

  const filteredProjects = projects.filter((project) =>
    matchesNameFilter(projectDisplayName(project), filterQuery),
  );

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold text-foreground">Projects</h1>
        <span
          data-testid="attention-badge"
          title="Combined awaiting-input + failed jobs across all Projects"
          className={
            attentionCount > 0
              ? "alarming flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400"
              : "neutral flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
          }
        >
          {attentionCount > 0 ? <AlertTriangle size={12} /> : null}
          {attentionCount}
        </span>
        <div className="flex-1" />
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus size={14} />
          New Project
        </Button>
      </div>
      <input
        type="text"
        value={filterQuery}
        onChange={(e) => setFilterQuery(e.target.value)}
        placeholder="Filter projects"
        aria-label="Filter projects"
        className="w-full max-w-sm rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      />
      {filteredProjects.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-muted-foreground">
          <p className="text-sm">No Projects match &quot;{filterQuery.trim()}&quot;</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredProjects.map((project) => (
            <ProjectCard key={project.id} project={project} onOpen={() => openProject(project)} />
          ))}
        </div>
      )}
      <CreateProjectDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(project) => {
          layoutContext?.onProjectCreated(project);
          setProjects((current) => [...current, {
            ...project,
            activeJobCount: 0,
            awaitingInputCount: 0,
            failedCount: 0,
            lastActivityAt: null,
          }]);
          navigate(`/projects/id/${encodeURIComponent(project.id)}`);
        }}
      />
    </div>
  );
}

