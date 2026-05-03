import { useMemo, useState } from "react";
import { Tooltip } from "../ui/tooltip";
import { ChevronDown, ChevronRight } from "lucide-react";
import { type FleetCostDriversResponse } from "../../api/client";
import { formatUsd } from "./helpers";
import { formatTokens, formatActivityBucket, ACTIVITY_DESCRIPTIONS } from "../MetricsPanelTypes";

// ---------------------------------------------------------------------------
// Fleet Cost Breakdown — mirrors per-job expandable card design
// ---------------------------------------------------------------------------

interface ActivityRow {
  bucket: string;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
  jobCount: number;
  avgCostPerJob: number;
}

export function FleetCostDriverInsights({ fleetDrivers }: { fleetDrivers: FleetCostDriversResponse }) {
  const activityRows = useMemo<ActivityRow[]>(() => {
    const summary = fleetDrivers.summary ?? [];
    return summary
      .filter((row) => row.dimension === "activity")
      .map((row) => ({
        bucket: row.bucket,
        costUsd: Number((row as any).costUsd ?? (row as any).cost_usd ?? 0),
        inputTokens: Number((row as any).inputTokens ?? (row as any).input_tokens ?? 0),
        outputTokens: Number((row as any).outputTokens ?? (row as any).output_tokens ?? 0),
        callCount: Number((row as any).callCount ?? (row as any).call_count ?? 0),
        jobCount: Number((row as any).jobCount ?? (row as any).job_count ?? 0),
        avgCostPerJob: Number((row as any).avgCostPerJob ?? (row as any).avg_cost_per_job ?? 0),
      }))
      .sort((a, b) => b.costUsd - a.costUsd);
  }, [fleetDrivers.summary]);

  const totalCost = useMemo(() => activityRows.reduce((s, r) => s + r.costUsd, 0), [activityRows]);
  const totalTurns = useMemo(() => activityRows.reduce((s, r) => s + r.callCount, 0), [activityRows]);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (bucket: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  };

  if (activityRows.length === 0) {
    return <p className="text-sm text-muted-foreground">No cost attribution data yet — complete a job to see breakdown.</p>;
  }

  return (
    <div className="space-y-2">
      {activityRows.map((row) => {
        const maxCost = activityRows[0]?.costUsd || 1;
        const widthPct = (row.costUsd / maxCost) * 100;
        const pct = totalCost > 0 ? ((row.costUsd / totalCost) * 100).toFixed(0) : "0";
        const isExpanded = expanded.has(row.bucket);
        const costPerTurn = row.callCount > 0 ? row.costUsd / row.callCount : 0;

        return (
          <div key={row.bucket} className="space-y-1">
            {/* Header row — clickable */}
            <div
              className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 hover:bg-accent/30 transition-colors"
              onClick={() => toggle(row.bucket)}
            >
              {isExpanded
                ? <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
                : <ChevronRight size={12} className="shrink-0 text-muted-foreground" />
              }
              <div className="flex-1 min-w-0">
                <Tooltip content={ACTIVITY_DESCRIPTIONS[row.bucket] ?? row.bucket}>
                  <div className="truncate text-foreground text-xs font-medium cursor-help border-b border-dotted border-muted-foreground/30 inline">
                    {formatActivityBucket(row.bucket)}
                  </div>
                </Tooltip>
                <div className="text-[10px] text-muted-foreground">
                  {row.callCount} turn{row.callCount !== 1 ? "s" : ""} · {pct}% of total · {row.jobCount} job{row.jobCount !== 1 ? "s" : ""}
                </div>
              </div>
              <div className="text-right tabular-nums shrink-0">
                <div className="text-xs">{formatUsd(row.costUsd)}</div>
                <div className="text-[10px] text-muted-foreground">{formatTokens(row.inputTokens + row.outputTokens)}</div>
              </div>
            </div>

            {/* Cost proportion bar */}
            <div className="h-1.5 rounded-full bg-muted overflow-hidden ml-5">
              <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.max(widthPct, 4)}%` }} />
            </div>

            {/* Expanded detail */}
            {isExpanded && (
              <div className="ml-7 space-y-2 pb-1 border-l border-border/50 pl-3">
                {ACTIVITY_DESCRIPTIONS[row.bucket] && (
                  <div className="text-[10px] text-muted-foreground/80 italic">
                    {ACTIVITY_DESCRIPTIONS[row.bucket]}
                  </div>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 text-[10px] text-muted-foreground">
                  <div>
                    <div className="text-muted-foreground/60">Input</div>
                    <div className="tabular-nums">{formatTokens(row.inputTokens)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground/60">Output</div>
                    <div className="tabular-nums">{formatTokens(row.outputTokens)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground/60">Cost/turn</div>
                    <div className="tabular-nums">{formatUsd(costPerTurn)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground/60">Avg/job</div>
                    <div className="tabular-nums">{formatUsd(row.avgCostPerJob)}</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Footer summary */}
      <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-2 border-t border-border/50">
        <span>{totalTurns} total turns across {activityRows.reduce((s, r) => Math.max(s, r.jobCount), 0)} jobs</span>
        <span className="tabular-nums font-medium">{formatUsd(totalCost)} total</span>
      </div>
    </div>
  );
}
