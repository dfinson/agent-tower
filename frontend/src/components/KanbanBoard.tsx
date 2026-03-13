import { useState, useCallback } from "react";
import {
  useTowerStore,
  selectActiveJobs,
  selectSignoffJobs,
  selectFailedJobs,
  selectHistoryJobs,
} from "../store";
import { KanbanColumn } from "./KanbanColumn";
import { fetchJobs } from "../api/client";
import { useShallow } from "zustand/react/shallow";

export function KanbanBoard() {
  const activeJobs = useTowerStore(useShallow(selectActiveJobs));
  const signoffJobs = useTowerStore(useShallow(selectSignoffJobs));
  const failedJobs = useTowerStore(useShallow(selectFailedJobs));
  const historyJobs = useTowerStore(useShallow(selectHistoryJobs));
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyHasMore, setHistoryHasMore] = useState(true);

  const loadMoreHistory = useCallback(async () => {
    try {
      const result = await fetchJobs({
        state: "succeeded,canceled",
        limit: 50,
        cursor: historyCursor ?? undefined,
      });
      const { dispatchSSEEvent } = useTowerStore.getState();
      for (const job of result.items) {
        dispatchSSEEvent("job_state_changed", {
          jobId: job.id,
          newState: job.state,
          timestamp: job.updatedAt,
        });
      }
      // Also upsert these jobs into the store
      useTowerStore.setState((state) => {
        const updated = { ...state.jobs };
        for (const job of result.items) {
          updated[job.id] = job;
        }
        return { jobs: updated };
      });
      setHistoryCursor(result.cursor);
      setHistoryHasMore(result.hasMore);
    } catch {
      // Silently fail — user can retry
    }
  }, [historyCursor]);

  return (
    <div className="kanban">
      <KanbanColumn title="Active" jobs={activeJobs} />
      <KanbanColumn title="Sign-off" jobs={signoffJobs} />
      <KanbanColumn title="Failed" jobs={failedJobs} />
      <KanbanColumn
        title="History"
        jobs={historyJobs}
        hasMore={historyHasMore}
        onLoadMore={loadMoreHistory}
      />
    </div>
  );
}
