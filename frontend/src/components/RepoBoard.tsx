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
import { fetchJobs } from "../api/client";
import { KanbanColumn } from "./KanbanColumn";
import { KanbanSkeleton } from "./KanbanSkeleton";
import { KANBAN_COLUMNS } from "../constants/kanban";
import { pathBasename } from "../lib/paths";

/**
 * Project-scoped Kanban board (Story 2.3 / CAP-1). Child route of the existing
 * `/repos/:repoPath` shell (AD-2) — `repoPath` is read from the URL, not client-only
 * state, so a refresh or shared link resolves to the same scoped board.
 *
 * A single-repo Project reduces to `job.repo === repoPath` (see Dev Notes on the
 * story file); once Story 2.2 wires multi-repo Project membership into the
 * frontend, only the repo-scoped selectors' filter needs to widen — this route and
 * component shape are unaffected.
 */
export function RepoBoard() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";
  const repoName = pathBasename(decoded) || decoded;

  const [loading, setLoading] = useState(true);
  const hasJobs = useStore((state) => Object.keys(state.jobs).length > 0);

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

  if (loading && !hasJobs) return <KanbanSkeleton />;

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
        <KanbanColumn title={KANBAN_COLUMNS.IN_PROGRESS} jobs={activeJobs} />
        <KanbanColumn title={KANBAN_COLUMNS.AWAITING_INPUT} jobs={signoffJobs} />
        <KanbanColumn title={KANBAN_COLUMNS.FAILED} jobs={attentionJobs} />
      </div>
    </div>
  );
}
