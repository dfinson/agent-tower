import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { type FleetLatencyDriversResponse } from "../../api/client";
import { Tooltip } from "../ui/tooltip";
import { formatActivityBucket, ACTIVITY_DESCRIPTIONS } from "../MetricsPanelTypes";

const CATEGORY_LABELS: Record<string, string> = {
  llm: "LLM wait",
  tool: "Tool execution",
  approval_wait: "Approval wait",
};

const CATEGORY_COLORS: Record<string, string> = {
  llm: "bg-indigo-500",
  tool: "bg-emerald-500",
  approval_wait: "bg-amber-500",
};

const TOOL_TYPE_LABELS: Record<string, string> = {
  shell: "Shell",
  agent: "Sub-agents",
  browser: "Browser",
  file_write: "File writes",
  file_read: "File reads",
  file_search: "Search",
  git_write: "Git",
  git_read: "Git (read)",
  bookkeeping: "Bookkeeping",
  thinking: "Thinking",
};

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

  // Tool type breakdown (shell, agent, browser, etc.) for expanded detail
  const toolTypeRows = useMemo<LatencyRow[]>(() => {
    const summary = fleetLatency.summary ?? [];
    return summary
      .filter((row) => row.dimension === "tool_type")
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

  // Category breakdown (llm/tool) for the LLM vs Tool time split
  const categoryRows = useMemo<LatencyRow[]>(() => {
    const summary = fleetLatency.summary ?? [];
    return summary
      .filter((row) => row.dimension === "category")
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
                    ACTIVITY_DESCRIPTIONS[row.bucket] ?? row.bucket
                  }
                >
                  <div className="truncate text-foreground text-xs font-medium cursor-help border-b border-dotted border-muted-foreground/30 inline">
                    {formatActivityBucket(row.bucket)}
                  </div>
                </Tooltip>
                <div className="text-[10px] text-muted-foreground">
                  {row.totalSpanCount.toLocaleString()} calls · {pct}% of time · {row.jobCount} job
                  {row.jobCount !== 1 ? "s" : ""}  
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
              <div className="ml-7 space-y-2 pb-1 border-l border-border/50 pl-3">
                {ACTIVITY_DESCRIPTIONS[row.bucket] && (
                  <div className="text-[10px] text-muted-foreground/80 italic">
                    {ACTIVITY_DESCRIPTIONS[row.bucket]}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2 text-[10px] text-muted-foreground">
                  <div>
                    Wall clock:{" "}
                    <span className="text-foreground">
                      {formatDurationCompact(row.avgWallClockMs)}
                    </span>
                  </div>
                  <div>
                    Sum duration:{" "}
                    <span className="text-foreground">
                      {formatDurationCompact(row.avgSumDurationMs)}
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

      {/* LLM vs Tool time split */}
      {categoryRows.length > 0 && (
        <div className="pt-3 mt-2 border-t border-border/50">
          <div className="text-[10px] font-medium text-muted-foreground mb-1.5">Time by type</div>
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted/40 mb-1.5">
            {categoryRows.map((c) => {
              const catTotal = categoryRows.reduce((s, r) => s + r.avgWallClockMs, 0);
              const w = catTotal > 0 ? (c.avgWallClockMs / catTotal) * 100 : 0;
              return (
                <Tooltip key={c.bucket} content={`${CATEGORY_LABELS[c.bucket] ?? c.bucket}: ${formatDurationCompact(c.avgWallClockMs)} avg/job`}>
                  <div
                    className={`h-full ${CATEGORY_COLORS[c.bucket] ?? "bg-gray-400"}`}
                    style={{ width: `${w}%` }}
                  />
                </Tooltip>
              );
            })}
          </div>
          <div className="flex gap-3 text-[10px] text-muted-foreground">
            {categoryRows.map((c) => (
              <span key={c.bucket} className="flex items-center gap-1">
                <span className={`inline-block h-2 w-2 rounded-sm ${CATEGORY_COLORS[c.bucket] ?? "bg-gray-400"}`} />
                {CATEGORY_LABELS[c.bucket] ?? c.bucket}: {formatDurationCompact(c.avgWallClockMs)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tool type breakdown */}
      {toolTypeRows.length > 0 && (
        <div className="pt-3 mt-1 border-t border-border/50">
          <div className="text-[10px] font-medium text-muted-foreground mb-1.5">Tool execution breakdown</div>
          <div className="space-y-0.5">
            {toolTypeRows.map((t) => {
              const maxToolMs = toolTypeRows[0]?.avgWallClockMs || 1;
              const barW = (t.avgWallClockMs / maxToolMs) * 100;
              return (
                <div key={t.bucket} className="flex items-center gap-2 text-[10px]">
                  <span className="w-16 truncate text-muted-foreground">{TOOL_TYPE_LABELS[t.bucket] ?? t.bucket}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted/40 overflow-hidden">
                    <div className="h-full rounded-full bg-emerald-500" style={{ width: `${barW}%` }} />
                  </div>
                  <span className="w-12 text-right tabular-nums text-muted-foreground">{formatDurationCompact(t.avgWallClockMs)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
