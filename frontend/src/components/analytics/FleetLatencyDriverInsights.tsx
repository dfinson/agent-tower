import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { type FleetLatencyDriversResponse } from "../../api/client";
import { Tooltip } from "../ui/tooltip";

const LATENCY_LABELS: Record<string, string> = {
  implementation: "Implementation",
  investigation: "Investigation",
  verification: "Verification",
  git_ops: "Git Operations",
  setup: "Setup",
  delegation: "Delegation",
  overhead: "Overhead",
  reasoning: "Reasoning",
  communication: "Communication",
  other: "Other",
};

const LATENCY_DESCRIPTIONS: Record<string, string> = {
  implementation: "Time spent on turns where the agent edited or created files",
  investigation: "Time spent reading code, searching, or exploring the codebase",
  verification: "Time spent running tests to validate changes",
  git_ops: "Time on git operations — commit, push, diff, status",
  setup: "Time installing dependencies or setting up the environment",
  delegation: "Time delegating work to sub-agents",
  overhead: "Time on internal housekeeping — todos, memory, intent tracking",
  reasoning: "Time on explicit thinking with no user-facing output",
  communication: "Time composing messages to the user",
  other: "Uncategorized latency",
};

function formatLatencyBucket(bucket: string): string {
  return LATENCY_LABELS[bucket] ?? bucket.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Fleet Latency Breakdown — mirrors FleetCostDriverInsights layout
// ---------------------------------------------------------------------------

function formatDurationCompact(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

interface LatencyRow {
  bucket: string;
  avgWallClockMs: number;
  avgSumDurationMs: number;
  totalSpanCount: number;
  jobCount: number;
  avgPctOfTotal: number;
}

export function FleetLatencyDriverInsights({
  fleetLatency,
}: {
  fleetLatency: FleetLatencyDriversResponse;
}) {
  const activityRows = useMemo<LatencyRow[]>(() => {
    const summary = fleetLatency.summary ?? [];
    return summary
      .filter((row) => row.dimension === "activity")
      .map((row) => ({
        bucket: row.bucket,
        avgWallClockMs: Number(row.avgWallClockMs ?? 0),
        avgSumDurationMs: Number(row.avgSumDurationMs ?? 0),
        totalSpanCount: Number(row.totalSpanCount ?? 0),
        jobCount: Number(row.jobCount ?? 0),
        avgPctOfTotal: Number(row.avgPctOfTotal ?? 0),
      }))
      .sort((a, b) => b.avgWallClockMs - a.avgWallClockMs);
  }, [fleetLatency.summary]);

  const totalMs = useMemo(
    () => activityRows.reduce((s, r) => s + r.avgWallClockMs, 0),
    [activityRows],
  );

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
    return (
      <p className="text-sm text-muted-foreground">
        No latency data yet — complete a job to see breakdown.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {/* Duration percentile summary */}
      {(fleetLatency.p50JobDurationMs > 0 || fleetLatency.avgJobDurationMs > 0) && (
        <div className="flex gap-4 text-xs text-muted-foreground mb-2">
          <span>Avg: {formatDurationCompact(fleetLatency.avgJobDurationMs)}</span>
          <span>p50: {formatDurationCompact(fleetLatency.p50JobDurationMs)}</span>
          <span>p95: {formatDurationCompact(fleetLatency.p95JobDurationMs)}</span>
        </div>
      )}

      {activityRows.map((row) => {
        const maxMs = activityRows[0]?.avgWallClockMs || 1;
        const widthPct = (row.avgWallClockMs / maxMs) * 100;
        const pct =
          totalMs > 0
            ? ((row.avgWallClockMs / totalMs) * 100).toFixed(0)
            : "0";
        const isExpanded = expanded.has(row.bucket);

        return (
          <div key={row.bucket} className="space-y-1">
            {/* Header row */}
            <div
              className="flex items-center gap-2 cursor-pointer rounded px-1 py-0.5 hover:bg-accent/30 transition-colors"
              onClick={() => toggle(row.bucket)}
            >
              {isExpanded ? (
                <ChevronDown
                  size={12}
                  className="shrink-0 text-muted-foreground"
                />
              ) : (
                <ChevronRight
                  size={12}
                  className="shrink-0 text-muted-foreground"
                />
              )}
              <div className="flex-1 min-w-0">
                <Tooltip
                  content={
                    LATENCY_DESCRIPTIONS[row.bucket] ?? row.bucket
                  }
                >
                  <div className="truncate text-foreground text-xs font-medium cursor-help border-b border-dotted border-muted-foreground/30 inline">
                    {formatLatencyBucket(row.bucket)}
                  </div>
                </Tooltip>
                <div className="text-[10px] text-muted-foreground">
                  {row.totalSpanCount} span
                  {row.totalSpanCount !== 1 ? "s" : ""} · {pct}% of time ·{" "}
                  {row.jobCount} job{row.jobCount !== 1 ? "s" : ""}
                </div>
              </div>
              <div className="text-right tabular-nums shrink-0">
                <div className="text-xs">
                  {formatDurationCompact(row.avgWallClockMs)}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  avg/job
                </div>
              </div>
            </div>

            {/* Latency proportion bar */}
            <div className="h-1.5 rounded-full bg-muted overflow-hidden ml-5">
              <div
                className="h-full rounded-full bg-amber-500"
                style={{ width: `${Math.max(widthPct, 4)}%` }}
              />
            </div>

            {/* Expanded detail */}
            {isExpanded && (
              <div className="ml-7 space-y-1 pb-1 border-l border-border/50 pl-3">
                <div className="grid grid-cols-2 gap-2 text-[10px] text-muted-foreground">
                  <div>
                    Sum duration:{" "}
                    <span className="text-foreground">
                      {formatDurationCompact(row.avgSumDurationMs)}
                    </span>
                  </div>
                  <div>
                    Spans:{" "}
                    <span className="text-foreground">
                      {row.totalSpanCount}
                    </span>
                  </div>
                  <div>
                    Jobs:{" "}
                    <span className="text-foreground">{row.jobCount}</span>
                  </div>
                  <div>
                    % of total:{" "}
                    <span className="text-foreground">
                      {row.avgPctOfTotal.toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
