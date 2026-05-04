import { Tooltip } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { formatActivityBucket, ACTIVITY_COLORS } from "../MetricsPanelTypes";

export interface ToolMixEntry {
  activity: string;
  count: number;
  pct: number;
  totalDurationMs: number;
}

export function ToolMix({ mix }: { mix: ToolMixEntry[] }) {
  if (!mix.length) return <p className="text-muted-foreground text-sm">No tool data yet.</p>;

  const maxCount = mix[0]?.count ?? 1;

  return (
    <div className="space-y-3">
      {/* Stacked bar overview */}
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted/40">
        {mix.map((entry) => (
          <Tooltip key={entry.activity} content={`${formatActivityBucket(entry.activity)}: ${entry.count.toLocaleString()} calls (${entry.pct}%)`}>
            <div
              className={cn("h-full", ACTIVITY_COLORS[entry.activity] ?? "bg-gray-400")}
              style={{ width: `${entry.pct}%` }}
            />
          </Tooltip>
        ))}
      </div>

      {/* Breakdown rows */}
      <div className="space-y-1.5">
        {mix.map((entry) => {
          const barWidth = (entry.count / maxCount) * 100;
          const label = formatActivityBucket(entry.activity);
          return (
            <div key={entry.activity} className="flex items-center gap-2 text-xs">
              <span className={cn("inline-block h-2.5 w-2.5 rounded-sm shrink-0", ACTIVITY_COLORS[entry.activity] ?? "bg-gray-400")} />
              <span className="w-24 truncate text-foreground font-medium">{label}</span>
              <div className="flex-1 h-2 rounded-full bg-muted/40 overflow-hidden">
                <div
                  className={cn("h-full rounded-full", ACTIVITY_COLORS[entry.activity] ?? "bg-gray-400")}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              <span className="w-10 text-right tabular-nums text-muted-foreground">{entry.pct}%</span>
              <span className="w-16 text-right tabular-nums text-muted-foreground/60">{entry.count.toLocaleString()}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
