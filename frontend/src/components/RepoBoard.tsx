import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, LayoutGrid } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import {
  useStore,
  enrichJob,
  selectActiveJobsForRepo,
  selectSignoffJobsForRepo,
  selectAttentionJobsForRepo,
} from "../store";
import type { JobSummary } from "../store";
import { fetchJobs, fetchProjects, fetchProjectTaskLinks } from "../api/client";
import type { TaskLinkResponse } from "../api/types";
import { KanbanColumn } from "./KanbanColumn";
import { KanbanSkeleton } from "./KanbanSkeleton";
import { TaskLinkCard } from "./TaskLinkCard";
import { KANBAN_COLUMNS } from "../constants/kanban";
import { pathBasename } from "../lib/paths";

/**
 * Determine whether a TaskLink's `dependsOn` list is fully satisfied (Story 4.4 / CAP-10).
 *
 * A composite `"{repoPath}::{storyNodeId}"` entry is satisfied when its target
 * TaskLink is found within the full Project TaskLink set (so cross-repo
 * dependencies resolve) and that target has a `jobId` whose Job has reached
 * the `completed` state. An unresolvable target, or one whose Job hasn't
 * completed, is unsatisfied. Empty `dependsOn` is trivially satisfied. This is
 * read-only render logic — it never triggers a spawn (Story 4.5's concern).
 */
function computeSatisfaction(
  taskLink: TaskLinkResponse,
  allTaskLinks: TaskLinkResponse[],
  jobs: Record<string, JobSummary>,
): { satisfied: boolean; blockingLabel: string | null } {
  if (taskLink.dependsOn.length === 0) return { satisfied: true, blockingLabel: null };

  const byKey = new Map<string, TaskLinkResponse>();
  for (const t of allTaskLinks) {
    if (t.storyNodeId) byKey.set(`${t.repoPath}::${t.storyNodeId}`, t);
  }

  for (const dep of taskLink.dependsOn) {
    const target = byKey.get(dep);
    const targetJob = target?.jobId ? jobs[target.jobId] : undefined;
    const depSatisfied = !!target && !!targetJob && targetJob.state === "completed";
    if (!depSatisfied) {
      const label = target?.storyNodeId ?? dep.split("::").pop() ?? dep;
      return { satisfied: false, blockingLabel: label };
    }
  }
  return { satisfied: true, blockingLabel: null };
}

/**
 * Project-scoped Kanban board (Story 2.3 / CAP-1). Child route of the existing
 * `/repos/:repoPath` shell (AD-2) — `repoPath` is read from the URL, not client-only
 * state, so a refresh or shared link resolves to the same scoped board.
 *
 * A single-repo Project reduces to `job.repo === repoPath` (see Dev Notes on the
 * story file); once Story 2.2 wires multi-repo Project membership into the
 * frontend, only the repo-scoped selectors' filter needs to widen — this route and
 * component shape are unaffected.
 *
 * Story 4.4 / CAP-10: also fetches the owning Project's TaskLinks (a second,
 * independent call — `GET /settings/projects/:id/task-links`, AD-11) and renders
 * them as chained-recipe cards in the "In Progress" column, alongside job cards,
 * in this same rendering pass.
 */
export function RepoBoard() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";
  const repoName = pathBasename(decoded) || decoded;

  const [loading, setLoading] = useState(true);
  const [taskLinks, setTaskLinks] = useState<TaskLinkResponse[]>([]);
  const hasJobs = useStore((state) => Object.keys(state.jobs).length > 0);
  const jobs = useStore((state) => state.jobs);

  const activeJobs = useStore(useShallow(selectActiveJobsForRepo(decoded)));
  const signoffJobs = useStore(useShallow(selectSignoffJobsForRepo(decoded)));
  const attentionJobs = useStore(useShallow(selectAttentionJobsForRepo(decoded)));

  useEffect(() => {
    if (!decoded) return;
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
  }, [decoded]);

  useEffect(() => {
    if (!decoded) return;
    let cancelled = false;
    fetchProjects()
      .then(async ({ items }) => {
        const owningProject = items.find((p) => p.repoPaths.includes(decoded));
        if (!owningProject) return;
        const { items: links } = await fetchProjectTaskLinks(owningProject.id);
        if (!cancelled) setTaskLinks(links);
      })
      .catch((err) => {
        if (!cancelled) console.error("Failed to fetch TaskLinks", err);
      });
    return () => { cancelled = true; };
  }, [decoded]);

  if (loading && !hasJobs) return <KanbanSkeleton />;

  const boardTaskLinks = taskLinks.filter((t) => t.repoPath === decoded);

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <Link
          to={`/repos/${encodeURIComponent(decoded)}`}
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
          <p className="text-sm text-muted-foreground truncate">{repoName}</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 h-[calc(100dvh-200px)] max-lg:grid-cols-2 max-sm:grid-cols-1">
        <KanbanColumn
          title={KANBAN_COLUMNS.IN_PROGRESS}
          jobs={activeJobs}
          extraCards={
            boardTaskLinks.length > 0 ? (
              <>
                {boardTaskLinks.map((taskLink) => {
                  const { satisfied, blockingLabel } = computeSatisfaction(taskLink, taskLinks, jobs);
                  return (
                    <TaskLinkCard
                      key={taskLink.id}
                      taskLink={taskLink}
                      satisfied={satisfied}
                      blockingLabel={blockingLabel}
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

