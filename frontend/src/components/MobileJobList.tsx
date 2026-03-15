import { useMemo, useState } from "react";
import { useTowerStore, selectJobs, selectApprovals } from "../store";
import type { JobSummary } from "../store";
import { JobCard } from "./JobCard";
import { cn } from "../lib/utils";

const TAB_STATES: Record<string, string[]> = {
  Active: ["queued", "running"],
  "Sign-off": ["waiting_for_approval"],
  Failed: ["failed"],
  History: ["succeeded", "canceled"],
};

const TABS = ["Active", "Sign-off", "Failed", "History"] as const;

function filterAndSort(jobs: Record<string, JobSummary>, states: string[]): JobSummary[] {
  return Object.values(jobs)
    .filter((j) => states.includes(j.state))
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

export function MobileJobList() {
  const [tab, setTab] = useState<string>("Active");
  const jobs = useTowerStore(selectJobs);
  const approvals = useTowerStore(selectApprovals);
  const pendingCount = Object.values(approvals).filter((a) => !a.resolvedAt).length;

  const filtered = useMemo(() => filterAndSort(jobs, TAB_STATES[tab] ?? []), [jobs, tab]);

  return (
    <div className="sm:hidden">
      <div className="flex rounded-lg bg-muted p-1 mb-4 gap-0.5">
        {TABS.map((t) => {
          const label = t === "Sign-off" && pendingCount > 0 ? `Sign-off (${pendingCount})` : t;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                tab === t
                  ? "bg-background text-foreground shadow"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>
      <div className="flex flex-col gap-2">
        {filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No {tab.toLowerCase()} jobs
          </p>
        ) : (
          filtered.map((job) => <JobCard key={job.id} job={job} />)
        )}
      </div>
    </div>
  );
}
