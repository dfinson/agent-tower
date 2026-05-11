import { Activity, Loader2 } from "lucide-react";
import { type ScorecardResponse } from "../../api/client";
import { Tooltip } from "../ui/tooltip";

// ---------------------------------------------------------------------------
// Activity card — raw resolution counts + animated running indicator
// ---------------------------------------------------------------------------

const OUTCOME_TIPS: Record<string, string> = {
  Running: "Jobs currently being worked on by an agent",
  "In Review": "Agent finished — changes waiting for your review",
  Merged: "Changes reviewed and merged into the target branch",
  "PR Created": "A pull request was opened for review",
  Discarded: "Changes reviewed but not applied",
  Failed: "Jobs that encountered an error",
  Cancelled: "Jobs manually stopped before completion",
};

export function ActivityCard({ scorecard }: { scorecard: ScorecardResponse }) {
  const a = scorecard.activity;
  const outcomes = [
    { label: "Running", count: a.running, color: "#3b82f6", spinning: true },
    { label: "In Review", count: a.inReview, color: "#8b5cf6" },
    { label: "Merged", count: a.merged, color: "#22c55e" },
    { label: "PR Created", count: a.prCreated, color: "#06b6d4" },
    { label: "Discarded", count: a.discarded, color: "#f59e0b" },
    { label: "Failed", count: a.failed, color: "#ef4444" },
    { label: "Cancelled", count: a.cancelled, color: "#6b7280" },
  ].filter((o) => o.count > 0);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Activity size={14} />
        Activity
      </div>

      <div className="text-2xl font-semibold text-foreground">
        {a.totalJobs} <span className="text-sm font-normal text-muted-foreground">jobs</span>
      </div>

      <div className="space-y-1.5">
        {outcomes.map((o) => (
          <Tooltip key={o.label} content={OUTCOME_TIPS[o.label] ?? o.label}>
            <div className="flex items-center justify-between text-xs cursor-help">
              <span className="flex items-center gap-1.5">
                {"spinning" in o && o.spinning ? (
                  <Loader2 size={10} className="animate-spin" style={{ color: o.color }} />
                ) : (
                  <span className="w-2 h-2 rounded-full" style={{ background: o.color }} />
                )}
                {o.label}
              </span>
              <span className="text-foreground font-medium">{o.count}</span>
            </div>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}
