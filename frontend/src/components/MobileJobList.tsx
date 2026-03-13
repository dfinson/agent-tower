import { useMemo, useState } from "react";
import { useTowerStore, selectJobs, selectApprovals } from "../store";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";
import { Tabs } from "../ui/Tabs";
import { EmptyState } from "../ui/Feedback";

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
  const [activeTab, setActiveTab] = useState("Active");
  const jobs = useTowerStore(selectJobs);
  const approvals = useTowerStore(selectApprovals);
  const pendingCount = Object.values(approvals).filter((a) => !a.resolvedAt).length;

  const filteredJobs = useMemo(
    () => filterAndSort(jobs, TAB_STATES[activeTab] ?? []),
    [jobs, activeTab]
  );

  return (
    <div className="sm:hidden">
      <Tabs
        tabs={[
          { id: "Active", label: "Active" },
          { id: "Sign-off", label: "Sign-off", badge: pendingCount },
          { id: "Failed", label: "Failed" },
          { id: "History", label: "History" },
        ]}
        active={activeTab}
        onChange={setActiveTab}
        className="mb-3"
      />
      {filteredJobs.length === 0 ? (
        <EmptyState text={`No ${activeTab.toLowerCase()} jobs`} />
      ) : (
        filteredJobs.map((job) => <JobCard key={job.id} job={job} />)
      )}
    </div>
  );
}
