import { Layers } from "lucide-react";
import { type CostAttributionBucket, type WasteBreakdown } from "../../api/client-analytics";
import { formatUsd } from "./helpers";
import { Tooltip } from "../ui/tooltip";

/**
 * Activity breakdown grouped into high-level categories.
 * Uses the activity dimension (100% per-job coverage) so the total
 * matches the Executive Summary and Budget.
 */

const GROUP_META: Record<string, { label: string; color: string; bg: string }> = {
  building: { label: "Building", color: "text-green-600", bg: "bg-green-500" },
  verifying: { label: "Verifying", color: "text-amber-600", bg: "bg-amber-500" },
  orienting: { label: "Orienting", color: "text-blue-600", bg: "bg-blue-500" },
  housekeeping: { label: "Housekeeping", color: "text-gray-600", bg: "bg-gray-400" },
  waste: { label: "Waste", color: "text-red-600", bg: "bg-red-500" },
};

/** Map activity-dimension bucket names to visual groups. */
const ACTIVITY_TO_GROUP: Record<string, string> = {
  implementation: "building",
  git_ops: "building",
  verification: "verifying",
  investigation: "orienting",
  communication: "orienting",
  setup: "housekeeping",
  overhead: "housekeeping",
};

const ACTIVITY_LABELS: Record<string, string> = {
  implementation: "Implementation",
  git_ops: "Git Operations",
  verification: "Verification",
  investigation: "Investigation",
  communication: "Communication",
  setup: "Setup",
  overhead: "Overhead",
};

interface Props {
  activityBuckets: CostAttributionBucket[];
  wasteBreakdown?: WasteBreakdown | null;
}

export function HierarchicalBreakdown({ activityBuckets, wasteBreakdown }: Props) {
  if (activityBuckets.length === 0 && !wasteBreakdown) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Layers size={14} />
          Activity Breakdown
        </div>
        <p className="text-muted-foreground text-sm mt-2">No activity data yet.</p>
      </div>
    );
  }

  // Build groups from activity dimension buckets
  const groups: Record<string, { cost: number; items: { name: string; cost: number }[] }> = {};
  for (const key of Object.keys(GROUP_META)) {
    groups[key] = { cost: 0, items: [] };
  }

  for (const bucket of activityBuckets) {
    const group = ACTIVITY_TO_GROUP[bucket.bucket] ?? "housekeeping";
    const cost = bucket.costUsd ?? 0;
    groups[group]!.cost += cost;
    groups[group]!.items.push({ name: bucket.bucket, cost });
  }

  // Add waste metrics (these overlap with activity totals — shown as informational sub-items)
  if (wasteBreakdown) {
    const wasteGroup = groups.waste!;
    if (wasteBreakdown.failedJobsUsd > 0) {
      wasteGroup.cost += wasteBreakdown.failedJobsUsd;
      wasteGroup.items.push({ name: "failed/discarded jobs", cost: wasteBreakdown.failedJobsUsd });
    }
    if (wasteBreakdown.retryUsd > 0) {
      wasteGroup.cost += wasteBreakdown.retryUsd;
      wasteGroup.items.push({ name: "retries", cost: wasteBreakdown.retryUsd });
    }
    if (wasteBreakdown.compactionUsd > 0) {
      wasteGroup.cost += wasteBreakdown.compactionUsd;
      wasteGroup.items.push({ name: "compaction", cost: wasteBreakdown.compactionUsd });
    }
    if (wasteBreakdown.rereadsUsd > 0) {
      wasteGroup.cost += wasteBreakdown.rereadsUsd;
      wasteGroup.items.push({ name: "redundant re-reads", cost: wasteBreakdown.rereadsUsd });
    }
  }

  // Total from activity dimension only (waste is a subset, not additive)
  const activityTotal = activityBuckets.reduce((s, b) => s + (b.costUsd ?? 0), 0);
  const orderedKeys = Object.keys(GROUP_META).filter((k) => groups[k]!.cost > 0);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Layers size={14} />
        Activity Breakdown
      </div>

      {/* Summary bar (uses activity total, excludes waste to avoid double-counting) */}
      <div className="flex h-3 rounded overflow-hidden">
        {orderedKeys.filter((k) => k !== "waste").map((key) => {
          const g = groups[key]!;
          const pct = activityTotal > 0 ? (g.cost / activityTotal) * 100 : 0;
          return pct > 0 ? (
            <Tooltip key={key} content={`${GROUP_META[key]!.label}: ${formatUsd(g.cost)} (${pct.toFixed(1)}%)`}>
              <div
                className={`${GROUP_META[key]!.bg} transition-all`}
                style={{ width: `${pct}%` }}
              />
            </Tooltip>
          ) : null;
        })}
      </div>

      {/* Activity groups */}
      {orderedKeys.map((key) => {
        const group = groups[key]!;
        const meta = GROUP_META[key]!;
        const pct = activityTotal > 0 ? (group.cost / activityTotal) * 100 : 0;
        return (
          <details key={key} className="group">
            <summary className="flex items-center justify-between cursor-pointer py-1">
              <span className={`font-medium text-sm ${meta.color}`}>{meta.label}</span>
              <span className="text-sm text-foreground">
                {formatUsd(group.cost)}{" "}
                {key !== "waste" && <span className="text-muted-foreground">({pct.toFixed(1)}%)</span>}
                {key === "waste" && <span className="text-muted-foreground text-xs">(included in above)</span>}
              </span>
            </summary>
            {group.items.length > 0 && (
              <div className="pl-4 mt-1 space-y-1">
                {group.items
                  .sort((a, b) => b.cost - a.cost)
                  .map((b) => (
                    <div key={b.name} className="flex justify-between text-xs text-muted-foreground">
                      <span>{ACTIVITY_LABELS[b.name] ?? b.name}</span>
                      <span>{formatUsd(b.cost)}</span>
                    </div>
                  ))}
              </div>
            )}
          </details>
        );
      })}
    </div>
  );
}
