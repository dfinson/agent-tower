import { useState } from "react";
import { Tooltip } from "../ui/tooltip";
import { cn } from "../../lib/utils";
import { formatActivityBucket, ACTIVITY_COLORS, ACTIVITY_DESCRIPTIONS } from "../MetricsPanelTypes";

export interface ToolMixToolDetail {
  name: string;
  count: number;
  pct: number;
}

export interface ToolMixEntry {
  activity: string;
  count: number;
  pct: number;
  totalDurationMs: number;
  tools: ToolMixToolDetail[];
}

export function ToolMix({ mix }: { mix: ToolMixEntry[] }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
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
      <div className="space-y-1">
        {mix.map((entry) => {
          const barWidth = (entry.count / maxCount) * 100;
          const label = formatActivityBucket(entry.activity);
          const description = ACTIVITY_DESCRIPTIONS[entry.activity];
          const isExpanded = expanded[entry.activity] ?? false;
          const hasTools = entry.tools && entry.tools.length > 0;

          return (
            <div key={entry.activity}>
              <div
                className={cn("flex items-center gap-2 text-xs", hasTools && "cursor-pointer hover:bg-muted/30 rounded px-1 -mx-1 py-0.5")}
                onClick={() => hasTools && setExpanded((s) => ({ ...s, [entry.activity]: !isExpanded }))}
              >
                {hasTools && (
                  <span className="text-[10px] text-muted-foreground/60 w-3 shrink-0">{isExpanded ? "▾" : "▸"}</span>
                )}
                <Tooltip content={description ?? entry.activity}>
                  <span className={cn("inline-block h-2.5 w-2.5 rounded-sm shrink-0", ACTIVITY_COLORS[entry.activity] ?? "bg-gray-400")} />
                </Tooltip>
                <Tooltip content={description ?? entry.activity}>
                  <span className="w-28 truncate text-foreground font-medium">{label}</span>
                </Tooltip>
                <div className="flex-1 h-2 rounded-full bg-muted/40 overflow-hidden">
                  <div
                    className={cn("h-full rounded-full", ACTIVITY_COLORS[entry.activity] ?? "bg-gray-400")}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
                <span className="w-10 text-right tabular-nums text-muted-foreground">{entry.pct}%</span>
                <span className="w-16 text-right tabular-nums text-muted-foreground/60">{entry.count.toLocaleString()}</span>
              </div>

              {/* Expanded tool detail */}
              {isExpanded && hasTools && (
                <div className="ml-8 mt-1 mb-2 space-y-0.5 border-l border-muted pl-3">
                  {entry.tools.map((tool) => (
                    <div key={tool.name} className="flex items-center gap-2 text-[11px]">
                      <span className="flex-1 truncate text-muted-foreground">{tool.name}</span>
                      <span className="w-10 text-right tabular-nums text-muted-foreground/80">{tool.pct}%</span>
                      <span className="w-14 text-right tabular-nums text-muted-foreground/50">{tool.count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
