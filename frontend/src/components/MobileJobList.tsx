import { useMemo, useState } from "react";
import { SegmentedControl, Stack, Text } from "@mantine/core";
import { useTowerStore, selectJobs, selectApprovals } from "../store";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";

const TAB_STATES: Record<string, string[]> = {
  Active: ["queued", "running"],
  "Sign-off": ["waiting_for_approval"],
  Failed: ["failed"],
  History: ["succeeded", "canceled"],
};

function filterAndSort(jobs: Record<string, JobSummary>, states: string[]): JobSummary[] {
  return Object.values(jobs)
    .filter((j) => states.includes(j.state))
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

export function MobileJobList() {
  const [tab, setTab] = useState("Active");
  const jobs = useTowerStore(selectJobs);
  const approvals = useTowerStore(selectApprovals);
  const pendingCount = Object.values(approvals).filter((a) => !a.resolvedAt).length;

  const filtered = useMemo(() => filterAndSort(jobs, TAB_STATES[tab] ?? []), [jobs, tab]);

  return (
    <div className="sm:hidden">
      <SegmentedControl
        value={tab}
        onChange={setTab}
        data={[
          { value: "Active", label: "Active" },
          { value: "Sign-off", label: pendingCount > 0 ? `Sign-off (${pendingCount})` : "Sign-off" },
          { value: "Failed", label: "Failed" },
          { value: "History", label: "History" },
        ]}
        fullWidth
        size="xs"
        mb="md"
      />
      <Stack gap="xs">
        {filtered.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">
            No {tab.toLowerCase()} jobs
          </Text>
        ) : (
          filtered.map((job) => <JobCard key={job.id} job={job} />)
        )}
      </Stack>
    </div>
  );
}
