import { useMemo, useState, useCallback } from "react";
import { useTowerStore, selectJobs } from "../store";
import type { JobSummary } from "../store";
import { KanbanColumn } from "./KanbanColumn";
import { fetchJobs } from "../api/client";

const COLUMN_STATES: Record<string, string[]> = {
  Active: ["queued", "running"],
  "Sign-off": ["waiting_for_approval"],
  Failed: ["failed"],
  History: ["succeeded", "canceled"],
};

function filterByStates(jobs: Record<string, JobSummary>, states: string[]): JobSummary[] {
  return Object.values(jobs)
    .filter((j) => states.includes(j.state))
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

export function KanbanBoard() {
  const jobs = useTowerStore(selectJobs);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyHasMore, setHistoryHasMore] = useState(true);

  const activeJobs = useMemo(() => filterByStates(jobs, COLUMN_STATES.Active ?? []), [jobs]);
  const signoffJobs = useMemo(() => filterByStates(jobs, COLUMN_STATES["Sign-off"] ?? []), [jobs]);
  const failedJobs = useMemo(() => filterByStates(jobs, COLUMN_STATES.Failed ?? []), [jobs]);
  const historyJobs = useMemo(() => filterByStates(jobs, COLUMN_STATES.History ?? []), [jobs]);

  const loadMoreHistory = useCallback(async () => {
    try {
      const result = await fetchJobs({ state: "succeeded,canceled", limit: 50, cursor: historyCursor ?? undefined });
      useTowerStore.setState((state) => {
        const updated = { ...state.jobs };
        for (const job of result.items) updated[job.id] = job;
        return { jobs: updated };
      });
      setHistoryCursor(result.cursor);
      setHistoryHasMore(result.hasMore);
    } catch { /* user can retry */ }
  }, [historyCursor]);

  return (
    <div className="grid grid-cols-4 gap-3 h-[calc(100vh-140px)] max-lg:grid-cols-2 max-sm:hidden">
      <KanbanColumn title="Active" jobs={activeJobs} />
      <KanbanColumn title="Sign-off" jobs={signoffJobs} />
      <KanbanColumn title="Failed" jobs={failedJobs} />
      <KanbanColumn title="History" jobs={historyJobs} hasMore={historyHasMore} onLoadMore={loadMoreHistory} />
    </div>
  );
}
