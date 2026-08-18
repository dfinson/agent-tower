import { useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Download, LayoutGrid, Plus } from "lucide-react";
import { toast } from "sonner";
import { useShallow } from "zustand/react/shallow";
import {
  useStore,
  enrichJob,
  selectActiveJobsForProject,
  selectSignoffJobsForProject,
  selectAttentionJobsForProject,
} from "../store";
import type { JobSummary } from "../store";
import { fetchJobs, fetchProject, fetchProjectTaskLinks, ingestProjectTasks, startTaskLink } from "../api/client";
import type { ProjectResponse, TaskLinkResponse } from "../api/types";
import { KanbanColumn } from "./KanbanColumn";
import { KanbanSkeleton } from "./KanbanSkeleton";
import { TaskLinkCard } from "./TaskLinkCard";
import { Button } from "./ui/button";
import { KANBAN_COLUMNS } from "../constants/kanban";

function lifecycleSignature(jobs: Record<string, JobSummary>, repoPaths: string[]): string {
  const memberRepos = new Set(repoPaths);
  return Object.values(jobs)
    .filter((job) => memberRepos.has(job.repo))
    .map((job) => `${job.id}:${job.state}`)
    .sort()
    .join("|");
}

function buildNewJobUrl(projectId: string | undefined, project: ProjectResponse | null): string {
  const params = new URLSearchParams();
  const singleRepoPath = project?.repoPaths.length === 1 ? project.repoPaths[0] : undefined;
  if (projectId) params.set("projectId", projectId);
  if (singleRepoPath) params.set("repo", singleRepoPath);
  const query = params.toString();
  return query ? `/jobs/new?${query}` : "/jobs/new";
}

/**
 * Project-scoped Kanban board (Story 2.3 / CAP-1). Child route of the
 * project-identity-keyed `/projects/id/:projectId` shell — `projectId` is
 * read from the URL, not client-only state, so a refresh or shared link
 * resolves to the same scoped board even after a Project's member repos change.
 *
 * Aggregates jobs across ALL of the Project's member repos (not just the
 * first), via the project-scoped selectors — a genuinely multi-repo Project's
 * board shows every member repo's jobs on one board.
 *
 * Story 4.4 / CAP-10: also fetches the owning Project's TaskLinks (a second,
 * independent call — `GET /settings/projects/:id/task-links`, AD-11) and renders
 * them as chained-recipe cards in the "In Progress" column, alongside job cards,
 * in this same rendering pass.
 */
export function RepoBoard() {
  const { projectId } = useParams<{ projectId: string }>();

  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [taskLinks, setTaskLinks] = useState<TaskLinkResponse[]>([]);
  const [ingesting, setIngesting] = useState(false);
  const [startingId, setStartingId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const currentProject = project?.id === projectId ? project : null;
  const repoPaths = currentProject?.repoPaths ?? [];
  const hasJobs = useStore((state) => Object.keys(state.jobs).length > 0);
  const jobLifecycleSignature = useStore((state) => lifecycleSignature(state.jobs, repoPaths));
  const reconciledLifecycleSignature = useRef<string | null>(null);

  const activeJobs = useStore(useShallow(selectActiveJobsForProject(repoPaths)));
  const signoffJobs = useStore(useShallow(selectSignoffJobsForProject(repoPaths)));
  const attentionJobs = useStore(useShallow(selectAttentionJobsForProject(repoPaths)));

  const newJobUrl = buildNewJobUrl(projectId, currentProject);

  useEffect(() => {
    let cancelled = false;
    setProject(null);
    setTaskLinks([]);
    setLoadError(null);
    setLoading(true);
    reconciledLifecycleSignature.current = null;

    if (!projectId) {
      setLoadError("No Project was selected.");
      setLoading(false);
      return () => { cancelled = true; };
    }

    const fetchEveryJob = async () => {
      const items: JobSummary[] = [];
      const seenCursors = new Set<string>();
      let cursor: string | undefined;
      do {
        const params: { limit: number; archived: boolean; cursor?: string } = {
          limit: 100,
          archived: false,
        };
        if (cursor) params.cursor = cursor;
        const page = await fetchJobs(params);
        items.push(...(page.items as JobSummary[]));
        const nextCursor = page.hasMore ? page.cursor ?? undefined : undefined;
        if (nextCursor && seenCursors.has(nextCursor)) {
          throw new Error("Job pagination returned a repeated cursor.");
        }
        if (nextCursor) seenCursors.add(nextCursor);
        cursor = nextCursor;
      } while (cursor);
      return items;
    };

    Promise.all([
      fetchProject(projectId),
      fetchEveryJob(),
      fetchProjectTaskLinks(projectId),
    ])
      .then(([nextProject, jobs, taskLinkResponse]) => {
        if (cancelled) return;
        setProject(nextProject);
        setTaskLinks(taskLinkResponse.items);
        useStore.setState((state) => {
          const updated = { ...state.jobs };
          for (const job of jobs) updated[job.id] = enrichJob(job);
          reconciledLifecycleSignature.current = lifecycleSignature(updated, nextProject.repoPaths);
          return { jobs: updated };
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setProject(null);
        setTaskLinks([]);
        setLoadError(err instanceof Error ? err.message : "Failed to load the Project board.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    if (!projectId || project?.id !== projectId) return;
    if (reconciledLifecycleSignature.current === jobLifecycleSignature) return;
    let cancelled = false;
    reconciledLifecycleSignature.current = jobLifecycleSignature;

    fetchProjectTaskLinks(projectId)
      .then((response) => {
        if (!cancelled) setTaskLinks(response.items);
      })
      .catch(() => {
        // Keep the last authoritative snapshot; a later lifecycle event retries.
      });

    return () => { cancelled = true; };
  }, [jobLifecycleSignature, project?.id, projectId]);

  if ((loading && !hasJobs) || (!loadError && project !== null && !currentProject)) {
    return <KanbanSkeleton />;
  }
  if (loadError) {
    return (
      <div role="alert" className="rounded-lg border border-red-500/40 bg-card p-8 text-center">
        <h1 className="text-lg font-semibold">Unable to load Project board</h1>
        <p className="mt-2 text-sm text-muted-foreground">{loadError}</p>
      </div>
    );
  }

  const handleIngest = async () => {
    if (!projectId) return;
    setIngesting(true);
    try {
      const result = await ingestProjectTasks(projectId);
      setTaskLinks(result.items);
      toast.success(`Ingested ${result.items.length} tasks.`);
    } catch (error) {
      toast.error(String(error));
    } finally {
      setIngesting(false);
    }
  };

  const handleStart = async (taskLink: TaskLinkResponse) => {
    if (!projectId) return;
    setStartingId(taskLink.id);
    try {
      const updated = await startTaskLink(projectId, taskLink.id);
      setTaskLinks((current) => current.map((item) => item.id === updated.id ? updated : item));
      toast.success(`Started ${updated.storyNodeId ?? updated.trackerTicketRef ?? "task"}.`);
    } catch (error) {
      toast.error(String(error));
    } finally {
      setStartingId(null);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link
          to={`/projects/id/${encodeURIComponent(projectId ?? "")}`}
          className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Back to overview"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <LayoutGrid size={16} className="text-muted-foreground" />
            Board
          </h1>
          <p className="text-sm text-muted-foreground truncate">{currentProject?.name ?? ""}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild size="sm">
            <Link to={newJobUrl}>
              <Plus size={14} />
              New Job
            </Link>
          </Button>
          <Button variant="outline" size="sm" disabled={ingesting} onClick={() => void handleIngest()}>
            <Download size={14} className={ingesting ? "animate-pulse" : ""} />
            {ingesting ? "Ingesting…" : "Ingest tasks"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 h-[calc(100dvh-200px)] max-lg:grid-cols-2 max-sm:grid-cols-1">
        <KanbanColumn
          title={KANBAN_COLUMNS.IN_PROGRESS}
          jobs={activeJobs}
          extraCards={
            taskLinks.length > 0 ? (
              <>
                {taskLinks.map((taskLink) => {
                  return (
                    <TaskLinkCard
                      key={taskLink.id}
                      taskLink={taskLink}
                      starting={startingId === taskLink.id}
                      onStart={(link) => void handleStart(link)}
                    />
                  );
                })}
              </>
            ) : undefined
          }
        />
        <KanbanColumn title={KANBAN_COLUMNS.AWAITING_INPUT} jobs={signoffJobs} />
        <KanbanColumn title={KANBAN_COLUMNS.FAILED} jobs={attentionJobs} />
      </div>
    </div>
  );
}
