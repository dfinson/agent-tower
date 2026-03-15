import { memo } from "react";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";
import { Button } from "./ui/button";

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
    <div className="flex flex-col overflow-hidden h-full rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-sm font-semibold text-muted-foreground">{title}</span>
        <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground">
          {jobs.length}
        </span>
      </div>

      <div className="flex flex-col gap-2 flex-1 overflow-y-auto p-2">
        {jobs.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No {title.toLowerCase()} jobs
          </p>
        ) : (
          jobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
        {hasMore && onLoadMore && (
          <Button variant="ghost" size="sm" className="w-full" onClick={onLoadMore}>
            Load more
          </Button>
        )}
      </div>
    </div>
  );
});
