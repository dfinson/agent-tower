import { LayoutGrid } from "lucide-react";
import { type ActivityPhaseMatrixResponse } from "../../api/client-analytics";
import { formatUsd } from "./helpers";

/**
 * Phase × Activity heatmap (Item 16).
 * Grid showing where each activity's cost falls within execution phases.
 */

const PHASE_ORDER = ["environment_setup", "agent_reasoning", "verification", "finalization", "post_completion"];
const PHASE_LABELS: Record<string, string> = {
  environment_setup: "Setup",
  agent_reasoning: "Active",
  verification: "Verify",
  finalization: "Final",
  post_completion: "Post",
};

interface Props {
  data: ActivityPhaseMatrixResponse | null;
}

export function ActivityPhaseHeatmap({ data }: Props) {
  if (!data?.cells?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <LayoutGrid size={14} />
          Phase × Activity
        </div>
        <p className="text-muted-foreground text-sm mt-2">No phase data yet.</p>
      </div>
    );
  }

  const activities = [...new Set(data.cells.map((c) => c.activity))].sort();
  const phases = PHASE_ORDER.filter((p) => data.cells.some((c) => c.phase === p));
  const maxCost = Math.max(...data.cells.map((c) => c.costUsd));

  const cellMap = new Map<string, typeof data.cells[0]>();
  for (const cell of data.cells) {
    cellMap.set(`${cell.activity}:${cell.phase}`, cell);
  }

  // Compute row totals for anomaly detection
  const rowTotals = new Map<string, number>();
  for (const activity of activities) {
    const total = data.cells
      .filter((c) => c.activity === activity)
      .reduce((s, c) => s + c.costUsd, 0);
    rowTotals.set(activity, total);
  }

  function cellColor(cost: number): string {
    if (maxCost <= 0) return "bg-muted/20";
    const ratio = cost / maxCost;
    if (ratio > 0.6) return "bg-red-200 dark:bg-red-900/40";
    if (ratio > 0.3) return "bg-amber-100 dark:bg-amber-900/30";
    if (ratio > 0.1) return "bg-green-100 dark:bg-green-900/20";
    return "bg-muted/20";
  }

  function isAnomaly(activity: string, cost: number): boolean {
    const total = rowTotals.get(activity) || 0;
    return total > 0 && cost / total > 0.25;
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <LayoutGrid size={14} />
        Phase × Activity Heatmap
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left p-1 text-muted-foreground font-medium">Activity</th>
              {phases.map((p) => (
                <th key={p} className="p-1 text-center text-muted-foreground font-medium">
                  {PHASE_LABELS[p] || p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activities.map((activity) => (
              <tr key={activity} className="border-t border-border/50">
                <td className="p-1 capitalize text-foreground">{activity.replace(/_/g, " ")}</td>
                {phases.map((phase) => {
                  const cell = cellMap.get(`${activity}:${phase}`);
                  const cost = cell?.costUsd ?? 0;
                  const anomaly = isAnomaly(activity, cost);
                  return (
                    <td
                      key={phase}
                      className={`p-1 text-center ${cellColor(cost)} ${anomaly ? "ring-1 ring-orange-400" : ""}`}
                      title={cell ? `${cell.callCount} turns, ${cell.jobCount} jobs` : ""}
                    >
                      {cost > 0 ? formatUsd(cost) : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
