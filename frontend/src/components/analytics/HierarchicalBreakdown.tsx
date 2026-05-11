import { Layers } from "lucide-react";
import { type CostDriversData } from "../MetricsPanelTypes";
import { formatUsd } from "./helpers";
import { Tooltip } from "../ui/tooltip";

/**
 * Hierarchical 2-level breakdown: L1 = Purpose, L2 = Action within purpose.
 * Uses the action_purpose cross-tab when available, falls back to action-only.
 */

const PURPOSE_META: Record<string, { label: string; color: string; bg: string }> = {
  building: { label: "Building", color: "text-green-600", bg: "bg-green-500" },
  recovering: { label: "Recovering", color: "text-red-600", bg: "bg-red-500" },
  orienting: { label: "Orienting", color: "text-blue-600", bg: "bg-blue-500" },
  verifying: { label: "Verifying", color: "text-amber-600", bg: "bg-amber-500" },
  housekeeping: { label: "Housekeeping", color: "text-gray-600", bg: "bg-gray-400" },
};

const ACTION_LABELS: Record<string, string> = {
  write: "Write",
  test: "Test",
  execute: "Execute",
  vcs: "VCS",
  delegate: "Delegate",
  read: "Read",
  think: "Think",
};

interface Props {
  data: CostDriversData | null;
  compactionCostUsd?: number;
}

export function HierarchicalBreakdown({ data, compactionCostUsd = 0 }: Props) {
  // Prefer actionPurpose cross-tab, fall back to purpose-only or action-only
  const apBuckets = data?.actionPurpose ?? [];
  const purposeBuckets = data?.purpose ?? [];

  const hasCrossTab = apBuckets.length > 0;
  const hasPurpose = purposeBuckets.length > 0;

  if (!hasCrossTab && !hasPurpose && !data?.action?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Layers size={14} />
          Purpose Breakdown
        </div>
        <p className="text-muted-foreground text-sm mt-2">No purpose data yet.</p>
      </div>
    );
  }

  // Build purpose groups with action sub-buckets
  const purposes: Record<string, { cost: number; actions: { name: string; cost: number }[] }> = {};
  for (const key of Object.keys(PURPOSE_META)) {
    purposes[key] = { cost: 0, actions: [] };
  }

  if (hasCrossTab) {
    for (const bucket of apBuckets) {
      // bucket format: "action:purpose"
      const colonIdx = bucket.bucket.indexOf(":");
      if (colonIdx < 0) continue;
      const action = bucket.bucket.slice(0, colonIdx);
      const purpose = bucket.bucket.slice(colonIdx + 1);
      const cost = bucket.costUsd ?? 0;
      if (!purposes[purpose]) {
        purposes[purpose] = { cost: 0, actions: [] };
      }
      purposes[purpose]!.cost += cost;
      purposes[purpose]!.actions.push({ name: action, cost });
    }
  } else if (hasPurpose) {
    for (const bucket of purposeBuckets) {
      const cost = bucket.costUsd ?? 0;
      if (!purposes[bucket.bucket]) {
        purposes[bucket.bucket] = { cost: 0, actions: [] };
      }
      purposes[bucket.bucket]!.cost += cost;
    }
  }

  // Add compaction to housekeeping
  if (compactionCostUsd > 0) {
    purposes.housekeeping!.cost += compactionCostUsd;
    purposes.housekeeping!.actions.push({ name: "compaction", cost: compactionCostUsd });
  }

  const total = Object.values(purposes).reduce((s, p) => s + p.cost, 0);
  const orderedKeys = Object.keys(PURPOSE_META).filter((k) => purposes[k]!.cost > 0);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Layers size={14} />
        Purpose Breakdown
      </div>

      {/* Summary bar */}
      <div className="flex h-3 rounded overflow-hidden">
        {orderedKeys.map((key) => {
          const p = purposes[key]!;
          const pct = total > 0 ? (p.cost / total) * 100 : 0;
          return pct > 0 ? (
            <Tooltip key={key} content={`${PURPOSE_META[key]!.label}: ${formatUsd(p.cost)} (${pct.toFixed(1)}%)`}>
              <div
                className={`${PURPOSE_META[key]!.bg} transition-all`}
                style={{ width: `${pct}%` }}
              />
            </Tooltip>
          ) : null;
        })}
      </div>

      {/* Purpose groups */}
      {orderedKeys.map((key) => {
        const purpose = purposes[key]!;
        const meta = PURPOSE_META[key]!;
        const pct = total > 0 ? (purpose.cost / total) * 100 : 0;
        return (
          <details key={key} className="group">
            <summary className="flex items-center justify-between cursor-pointer py-1">
              <span className={`font-medium text-sm ${meta.color}`}>{meta.label}</span>
              <span className="text-sm text-foreground">
                {formatUsd(purpose.cost)} <span className="text-muted-foreground">({pct.toFixed(1)}%)</span>
              </span>
            </summary>
            {purpose.actions.length > 0 && (
              <div className="pl-4 mt-1 space-y-1">
                {purpose.actions
                  .sort((a, b) => b.cost - a.cost)
                  .map((b) => (
                    <div key={b.name} className="flex justify-between text-xs text-muted-foreground">
                      <span>{ACTION_LABELS[b.name] ?? b.name}</span>
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
