import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Download, LayoutGrid } from "lucide-react";
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
  const hasJobs = useStore((state) => Object.keys(state.jobs).length > 0);

  const repoPaths = project?.repoPaths ?? [];
  const activeJobs = useStore(useShallow(selectActiveJobsForProject(repoPaths)));
  const signoffJobs = useStore(useShallow(selectSignoffJobsForProject(repoPaths)));
  const attentionJobs = useStore(useShallow(selectAttentionJobsForProject(repoPaths)));

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    fetchProject(projectId)
      .then((proj) => { if (!cancelled) setProject(proj); })
      .catch((err) => { if (!cancelled) console.error("Failed to fetch Project", err); });
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    fetchJobs({ limit: 100, archived: false })
      .then((result) => {
        if (cancelled) return;
        useStore.setState((state) => {
          const updated = { ...state.jobs };
          for (const job of result.items) updated[job.id] = enrichJob(job as JobSummary);
          return { jobs: updated };
        });
      })
      .catch((err) => {
        if (!cancelled) console.error("Failed to fetch jobs", err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    fetchProjectTaskLinks(projectId)
      .then(({ items: links }) => { if (!cancelled) setTaskLinks(links); })
      .catch((err) => {
        if (!cancelled) console.error("Failed to fetch TaskLinks", err);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading && !hasJobs) return <KanbanSkeleton />;

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
          <p className="text-sm text-muted-foreground truncate">{project?.name ?? ""}</p>
        </div>
        <Button variant="outline" size="sm" disabled={ingesting} onClick={() => void handleIngest()}>
          <Download size={14} className={ingesting ? "animate-pulse" : ""} />
          {ingesting ? "Ingesting…" : "Ingest tasks"}
        </Button>
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
