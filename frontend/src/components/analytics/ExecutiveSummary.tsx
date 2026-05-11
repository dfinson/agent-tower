import { PieChart } from "lucide-react";
import { type ExecutiveSummaryResponse } from "../../api/client-analytics";
import { formatUsd } from "./helpers";

/**
 * 3-bucket executive summary donut (Item 18).
 * Building (green) / Thinking (blue) / Wasted (red).
 */

interface Props {
  data: ExecutiveSummaryResponse | null;
}

export function ExecutiveSummary({ data }: Props) {
  if (!data || data.totalUsd <= 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <PieChart size={14} />
          Executive Summary
        </div>
        <p className="text-muted-foreground text-sm mt-2">No spend data yet.</p>
      </div>
    );
  }

  const segments = [
    { key: "building", label: "Building", pct: data.buildingPct, usd: data.buildingUsd, color: "text-green-600", bg: "bg-green-500", ring: "#22c55e", tooltip: "Writing code, running tests, executing commands, and delegating to sub-agents — direct productive output" },
    { key: "thinking", label: "Thinking", pct: data.thinkingPct, usd: data.thinkingUsd, color: "text-blue-600", bg: "bg-blue-500", ring: "#3b82f6", tooltip: "Reading files, reasoning about approach, gathering context — preparatory work that enables building" },
    { key: "wasted", label: "Wasted", pct: data.wastedPct, usd: data.wastedUsd, color: "text-red-600", bg: "bg-red-500", ring: "#ef4444", tooltip: "Retries, failed/discarded jobs, context compaction, and redundant file re-reads — spend without value" },
  ];

  // SVG donut
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <PieChart size={14} />
        Executive Summary
      </div>

      <div className="flex items-center gap-6">
        {/* Donut */}
        <div className="relative w-24 h-24 flex-shrink-0">
          <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
            {segments.map((seg) => {
              const dashLen = (seg.pct / 100) * circumference;
              const dashGap = circumference - dashLen;
              const el = (
                <circle
                  key={seg.key}
                  cx="50"
                  cy="50"
                  r={radius}
                  fill="none"
                  stroke={seg.ring}
                  strokeWidth="12"
                  strokeDasharray={`${dashLen} ${dashGap}`}
                  strokeDashoffset={-offset}
                />
              );
              offset += dashLen;
              return el;
            })}
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-xs font-semibold text-foreground">{formatUsd(data.totalUsd)}</span>
          </div>
        </div>

        {/* Legend */}
        <div className="space-y-2 flex-1">
          {segments.map((seg) => (
            <div key={seg.key} className="flex items-center justify-between group relative">
              <div className="flex items-center gap-2">
                <span className={`w-3 h-3 rounded ${seg.bg}`} />
                <span className={`text-sm font-medium ${seg.color} cursor-help`} title={seg.tooltip}>{seg.label}</span>
              </div>
              <div className="text-right">
                <span className="text-sm text-foreground">{formatUsd(seg.usd)}</span>
                <span className="text-xs text-muted-foreground ml-1">({seg.pct.toFixed(1)}%)</span>
              </div>
              <div className="absolute left-0 -bottom-1 translate-y-full z-50 hidden group-hover:block w-64 p-2 rounded bg-popover border border-border shadow-lg text-xs text-popover-foreground">
                {seg.tooltip}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Waste breakdown */}
      {data.wastedUsd > 0 && data.wasteBreakdown && (
        <details className="text-xs">
          <summary className="cursor-pointer text-red-500 font-medium">Waste breakdown</summary>
          <div className="pl-4 mt-1 space-y-0.5 text-muted-foreground">
            {data.wasteBreakdown.retryUsd > 0 && (
              <div className="flex justify-between">
                <span>Retries</span>
                <span>{formatUsd(data.wasteBreakdown.retryUsd)}</span>
              </div>
            )}
            {data.wasteBreakdown.failedJobsUsd > 0 && (
              <div className="flex justify-between">
                <span>Failed/discarded jobs</span>
                <span>{formatUsd(data.wasteBreakdown.failedJobsUsd)}</span>
              </div>
            )}
            {data.wasteBreakdown.compactionUsd > 0 && (
              <div className="flex justify-between">
                <span>Compaction overhead</span>
                <span>{formatUsd(data.wasteBreakdown.compactionUsd)}</span>
              </div>
            )}
            {data.wasteBreakdown.rereadsUsd > 0 && (
              <div className="flex justify-between">
                <span>File re-reads</span>
                <span>{formatUsd(data.wasteBreakdown.rereadsUsd)}</span>
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
