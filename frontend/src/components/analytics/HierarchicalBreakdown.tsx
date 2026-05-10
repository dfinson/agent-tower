import { Layers } from "lucide-react";
import { type CostDriversData } from "../MetricsPanelTypes";
import { formatUsd } from "./helpers";

/**
 * Hierarchical 2-level breakdown of activity costs (Item 13).
 * Groups flat activity buckets into 3 pillars: Productive / Preparatory / Overhead.
 */

const ACTIVITY_TO_PILLAR: Record<string, string> = {
  implementation: "productive",
  feature_dev: "productive",
  debugging: "productive",
  refactoring: "productive",
  verification: "productive",
  git_ops: "productive",
  investigation: "preparatory",
  setup: "preparatory",
  reasoning: "preparatory",
  communication: "overhead",
  delegation: "overhead",
  overhead: "overhead",
};

const PILLAR_META: Record<string, { label: string; color: string; bg: string }> = {
  productive: { label: "Productive Work", color: "text-green-600", bg: "bg-green-500" },
  preparatory: { label: "Preparatory Work", color: "text-blue-600", bg: "bg-blue-500" },
  overhead: { label: "Overhead", color: "text-amber-600", bg: "bg-amber-500" },
};

interface Props {
  data: CostDriversData | null;
  compactionCostUsd?: number;
}

export function HierarchicalBreakdown({ data, compactionCostUsd = 0 }: Props) {
  if (!data?.activity?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Layers size={14} />
          Activity Hierarchy
        </div>
        <p className="text-muted-foreground text-sm mt-2">No activity data yet.</p>
      </div>
    );
  }

  // Group buckets by pillar
  const pillars: Record<string, { cost: number; buckets: { name: string; cost: number }[] }> = {
    productive: { cost: 0, buckets: [] },
    preparatory: { cost: 0, buckets: [] },
    overhead: { cost: 0, buckets: [] },
  };

  for (const bucket of data.activity) {
    const pillar = ACTIVITY_TO_PILLAR[bucket.bucket] || "overhead";
    const cost = bucket.costUsd ?? 0;
    pillars[pillar]!.cost += cost;
    pillars[pillar]!.buckets.push({ name: bucket.bucket, cost });
  }

  // Add compaction to overhead
  if (compactionCostUsd > 0) {
    pillars.overhead!.cost += compactionCostUsd;
    pillars.overhead!.buckets.push({ name: "compaction", cost: compactionCostUsd });
  }

  const total = Object.values(pillars).reduce((s, p) => s + p.cost, 0);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Layers size={14} />
        Activity Hierarchy
      </div>

      {/* Summary bar */}
      <div className="flex h-3 rounded overflow-hidden">
        {(["productive", "preparatory", "overhead"] as const).map((key) => {
          const p = pillars[key]!;
          const pct = total > 0 ? (p.cost / total) * 100 : 0;
          return pct > 0 ? (
            <div
              key={key}
              className={`${PILLAR_META[key]!.bg} transition-all`}
              style={{ width: `${pct}%` }}
              title={`${PILLAR_META[key]!.label}: ${pct.toFixed(1)}%`}
            />
          ) : null;
        })}
      </div>

      {/* Pillars */}
      {(["productive", "preparatory", "overhead"] as const).map((key) => {
        const pillar = pillars[key]!;
        if (pillar.cost <= 0) return null;
        const meta = PILLAR_META[key]!;
        const pct = total > 0 ? (pillar.cost / total) * 100 : 0;
        return (
          <details key={key} className="group">
            <summary className="flex items-center justify-between cursor-pointer py-1">
              <span className={`font-medium text-sm ${meta.color}`}>{meta.label}</span>
              <span className="text-sm text-foreground">
                {formatUsd(pillar.cost)} <span className="text-muted-foreground">({pct.toFixed(1)}%)</span>
              </span>
            </summary>
            <div className="pl-4 mt-1 space-y-1">
              {pillar.buckets
                .sort((a, b) => b.cost - a.cost)
                .map((b) => (
                  <div key={b.name} className="flex justify-between text-xs text-muted-foreground">
                    <span className="capitalize">{b.name.replace(/_/g, " ")}</span>
                    <span>{formatUsd(b.cost)}</span>
                  </div>
                ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}
