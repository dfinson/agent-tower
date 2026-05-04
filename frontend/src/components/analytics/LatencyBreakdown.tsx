import { useMemo } from "react";
import type { LatencyBucket } from "../MetricsPanelTypes";

// ---------------------------------------------------------------------------
// Per-Job Latency Breakdown — stacked waterfall by category
// ---------------------------------------------------------------------------

export type LatencyBucketData = LatencyBucket;

interface Props {
  categoryBuckets: LatencyBucketData[];
  totalDurationMs: number;
  idleMs: number;
  parallelismRatio: number;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

const CATEGORY_COLORS: Record<string, string> = {
  llm: "bg-violet-500",
  tool: "bg-amber-500",
  approval_wait: "bg-red-400",
  other: "bg-slate-400",
  idle: "bg-slate-600",
};

const CATEGORY_LABELS: Record<string, string> = {
  llm: "LLM Wait",
  tool: "Tool Execution",
  approval_wait: "Approval Wait",
  other: "Other",
  idle: "Idle / Overhead",
};

export function LatencyBreakdown({
  categoryBuckets,
  totalDurationMs,
  idleMs,
  parallelismRatio,
}: Props) {
  const segments = useMemo(() => {
    const sorted = [...categoryBuckets].sort(
      (a, b) => b.wallClockMs - a.wallClockMs,
    );
    // Add idle as a synthetic segment
    const all = [
      ...sorted,
      ...(idleMs > 0
        ? [
            {
              dimension: "category",
              bucket: "idle",
              wallClockMs: idleMs,
              sumDurationMs: idleMs,
              spanCount: 0,
              p50Ms: 0,
              p95Ms: 0,
              maxMs: 0,
              pctOfTotal:
                totalDurationMs > 0 ? (idleMs / totalDurationMs) * 100 : 0,
            },
          ]
        : []),
    ];
    return all;
  }, [categoryBuckets, idleMs, totalDurationMs]);

  if (totalDurationMs <= 0 || segments.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="h-4 rounded-full bg-muted overflow-hidden flex">
        {segments.map((seg) => {
          const pct =
            totalDurationMs > 0
              ? (seg.wallClockMs / totalDurationMs) * 100
              : 0;
          if (pct < 1) return null;
          return (
            <div
              key={seg.bucket}
              className={`h-full ${CATEGORY_COLORS[seg.bucket] ?? "bg-slate-400"} first:rounded-l-full last:rounded-r-full`}
              style={{ width: `${pct}%` }}
              title={`${CATEGORY_LABELS[seg.bucket] ?? seg.bucket}: ${formatDuration(seg.wallClockMs)} (${pct.toFixed(0)}%)`}
            />
          );
        })}
      </div>

      {/* Legend + details */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {segments.map((seg) => {
          const pct =
            totalDurationMs > 0
              ? (seg.wallClockMs / totalDurationMs) * 100
              : 0;
          return (
            <div
              key={seg.bucket}
              className="flex items-center gap-1.5 text-[10px]"
            >
              <div
                className={`w-2 h-2 rounded-sm ${CATEGORY_COLORS[seg.bucket] ?? "bg-slate-400"}`}
              />
              <span className="text-muted-foreground">
                {CATEGORY_LABELS[seg.bucket] ?? seg.bucket}
              </span>
              <span className="text-foreground ml-auto tabular-nums">
                {formatDuration(seg.wallClockMs)}
              </span>
              <span className="text-muted-foreground tabular-nums">
                ({pct.toFixed(0)}%)
              </span>
            </div>
          );
        })}
      </div>

      {/* Parallelism indicator */}
      {parallelismRatio > 1.1 && (
        <div className="text-[10px] text-muted-foreground">
          Parallelism ratio:{" "}
          <span className="text-foreground">
            {parallelismRatio.toFixed(2)}x
          </span>{" "}
          — spans overlapped in time
        </div>
      )}

      {/* P95 stats for non-idle categories */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        {categoryBuckets
          .filter((b) => b.spanCount > 0)
          .sort((a, b) => b.p95Ms - a.p95Ms)
          .map((seg) => (
            <div
              key={seg.bucket}
              className="flex items-center gap-1 text-[10px] text-muted-foreground"
            >
              <span>{CATEGORY_LABELS[seg.bucket] ?? seg.bucket} p95:</span>
              <span className="text-foreground tabular-nums">
                {formatDuration(seg.p95Ms)}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}
