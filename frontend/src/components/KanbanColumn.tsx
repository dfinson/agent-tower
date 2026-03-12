import { memo } from "react";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";

interface KanbanColumnProps {
  title: string;
  jobs: JobSummary[];
  onLoadMore?: () => void;
  hasMore?: boolean;
}

export const KanbanColumn = memo(function KanbanColumn({
  title,
  jobs,
  onLoadMore,
  hasMore,
}: KanbanColumnProps) {
  return (
    <div className="kanban-column">
      <div className="kanban-column__header">
        <span>{title}</span>
        <span className="kanban-column__count">{jobs.length}</span>
      </div>
      <div className="kanban-column__list">
        {jobs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__text">No jobs</div>
          </div>
        ) : (
          jobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
        {hasMore && onLoadMore && (
          <button
            className="btn btn--sm"
            style={{ width: "100%", marginTop: 8 }}
            onClick={onLoadMore}
          >
            Load more
          </button>
        )}
      </div>
    </div>
  );
});
