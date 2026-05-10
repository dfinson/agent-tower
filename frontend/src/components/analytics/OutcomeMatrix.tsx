import { Grid3x3 } from "lucide-react";
import { type OutcomeMatrixResponse } from "../../api/client-analytics";
import { formatUsd } from "./helpers";

/**
 * Outcome-weighted efficiency matrix (Item 15).
 * Heatmap: activity rows × resolution columns, colored by cost intensity.
 */

const RESOLUTION_ORDER = ["merged", "pr_created", "completed", "running", "failed", "discarded", "cancelled"];
const RESOLUTION_LABELS: Record<string, string> = {
  merged: "Merged",
  pr_created: "PR'd",
  completed: "Done",
  running: "Running",
  failed: "Failed",
  discarded: "Discarded",
  cancelled: "Cancelled",
};

interface Props {
  data: OutcomeMatrixResponse | null;
}

export function OutcomeMatrix({ data }: Props) {
  if (!data?.cells?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Grid3x3 size={14} />
          Outcome Matrix
        </div>
        <p className="text-muted-foreground text-sm mt-2">No outcome data yet.</p>
      </div>
    );
  }

  // Build matrix
  const activities = [...new Set(data.cells.map((c) => c.activity))];
  const resolutions = RESOLUTION_ORDER.filter((r) =>
    data.cells.some((c) => c.resolution === r),
  );
  const maxCost = Math.max(...data.cells.map((c) => c.costUsd));

  const cellMap = new Map<string, typeof data.cells[0]>();
  for (const cell of data.cells) {
    cellMap.set(`${cell.activity}:${cell.resolution}`, cell);
  }

  function intensityClass(cost: number): string {
    if (maxCost <= 0) return "bg-muted/20";
    const ratio = cost / maxCost;
    if (ratio > 0.7) return "bg-red-200 dark:bg-red-900/40";
    if (ratio > 0.4) return "bg-amber-100 dark:bg-amber-900/30";
    if (ratio > 0.1) return "bg-yellow-50 dark:bg-yellow-900/20";
    return "bg-muted/20";
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Grid3x3 size={14} />
          Outcome Matrix
        </div>
        {data.totalWasteUsd > 0 && (
          <span className="text-xs text-red-500 font-medium">
            Waste: {formatUsd(data.totalWasteUsd)}
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left p-1 text-muted-foreground font-medium">Activity</th>
              {resolutions.map((r) => (
                <th
                  key={r}
                  className={`p-1 text-center font-medium ${
                    r === "failed" || r === "discarded" ? "text-red-500" : "text-muted-foreground"
                  }`}
                >
                  {RESOLUTION_LABELS[r] || r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activities.sort().map((activity) => (
              <tr key={activity} className="border-t border-border/50">
                <td className="p-1 capitalize text-foreground">{activity.replace(/_/g, " ")}</td>
                {resolutions.map((res) => {
                  const cell = cellMap.get(`${activity}:${res}`);
                  const cost = cell?.costUsd ?? 0;
                  return (
                    <td
                      key={res}
                      className={`p-1 text-center ${intensityClass(cost)}`}
                      title={cell ? `${cell.jobCount} jobs` : ""}
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
