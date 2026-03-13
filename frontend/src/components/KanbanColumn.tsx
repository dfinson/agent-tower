import { memo } from "react";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";
import { Card, CardHeader, CardTitle, CardCount } from "../ui/Card";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/Feedback";

interface KanbanColumnProps {
  title: string;
  jobs: JobSummary[];
  onLoadMore?: () => void;
  hasMore?: boolean;
}

export const KanbanColumn = memo(function KanbanColumn({ title, jobs, onLoadMore, hasMore }: KanbanColumnProps) {
  return (
    <Card className="flex flex-col overflow-hidden">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardCount count={jobs.length} />
      </CardHeader>
      <div className="flex-1 overflow-y-auto p-2">
        {jobs.length === 0 ? (
          <EmptyState text="No jobs" />
        ) : (
          jobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
        {hasMore && onLoadMore && (
          <Button size="sm" className="w-full mt-2" onClick={onLoadMore}>
            Load more
          </Button>
        )}
      </div>
    </Card>
  );
});
