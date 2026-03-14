import { memo } from "react";
import { Paper, Group, Text, Badge, Stack, Button } from "@mantine/core";
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
    <Paper className="flex flex-col overflow-hidden h-full" radius="lg" p={0}>
      <Group
        justify="space-between"
        className="px-4 py-3 border-b border-[var(--mantine-color-dark-4)]"
      >
        <Text size="sm" fw={600} c="dimmed">
          {title}
        </Text>
        <Badge variant="default" size="sm" radius="xl">
          {jobs.length}
        </Badge>
      </Group>

      <Stack gap="xs" className="flex-1 overflow-y-auto p-2">
        {jobs.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">
            No jobs
          </Text>
        ) : (
          jobs.map((job) => <JobCard key={job.id} job={job} />)
        )}
        {hasMore && onLoadMore && (
          <Button variant="subtle" size="xs" fullWidth onClick={onLoadMore}>
            Load more
          </Button>
        )}
      </Stack>
    </Paper>
  );
});
