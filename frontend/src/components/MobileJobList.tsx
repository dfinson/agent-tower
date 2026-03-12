import { useMemo, useState } from "react";
import { useTowerStore, selectJobs, selectApprovals } from "../store";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";

const TABS = ["Active", "Sign-off", "Failed", "History"] as const;
type Tab = (typeof TABS)[number];

const TAB_STATES: Record<Tab, string[]> = {
  Active: ["queued", "running"],
  "Sign-off": ["waiting_for_approval"],
  Failed: ["failed"],
  History: ["succeeded", "canceled"],
};

function filterAndSort(
  jobs: Record<string, JobSummary>,
  states: string[],
): JobSummary[] {
  return Object.values(jobs)
    .filter((j) => states.includes(j.state))
    .sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
    );
}

export function MobileJobList() {
  const [activeTab, setActiveTab] = useState<Tab>("Active");
  const jobs = useTowerStore(selectJobs);
  const approvals = useTowerStore(selectApprovals);

  const filteredJobs = useMemo(
    () => filterAndSort(jobs, TAB_STATES[activeTab]),
    [jobs, activeTab],
  );

  const pendingApprovalCount = Object.values(approvals).filter(
    (a) => !a.resolvedAt,
  ).length;

  return (
    <div className="mobile-job-list">
      <div className="filter-tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`filter-tab ${activeTab === tab ? "filter-tab--active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
            {tab === "Sign-off" && pendingApprovalCount > 0 && (
              <span className="filter-tab__badge">{pendingApprovalCount}</span>
            )}
          </button>
        ))}
      </div>
      {filteredJobs.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__text">No {activeTab.toLowerCase()} jobs</div>
        </div>
      ) : (
        filteredJobs.map((job) => <JobCard key={job.id} job={job} />)
      )}
    </div>
  );
}
