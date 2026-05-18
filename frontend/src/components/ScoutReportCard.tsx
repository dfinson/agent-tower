/**
 * ScoutReportCard — 3-level progressive disclosure of preflight scout activity.
 *
 * Level 1: One-line summary in the ActivityTimeline header
 * Level 2: Expanded report card with tool call stats
 * Level 3: Full exploration log with collapsible tool calls
 */

import { useState, memo } from "react";
import {
  Telescope, ChevronDown, ChevronRight, CheckCircle2, Loader2,
  Wrench, Clock, FileText,
} from "lucide-react";
import { cn } from "../lib/utils";
import type { PreflightReport } from "../store";

/** Human-readable labels for CodeRecon tool names. */
const TOOL_LABELS: Record<string, string> = {
  recon_understand: "Codebase overview",
  recon_impact: "Reference analysis",
  checkpoint: "Checkpoint",
  graph_communities: "Communities",
  graph_cycles: "Cycles",
  semantic_diff: "Structural diff",
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Level 1: Compact one-line summary for the activity timeline header. */
export const ScoutSummaryLine = memo(function ScoutSummaryLine({
  report,
  status,
}: {
  report: PreflightReport | null;
  status: "active" | "done";
}) {
  if (!report || status === "active") {
    const toolCount = report?.toolCalls.length ?? 0;
    return (
      <div className="flex items-center gap-1.5">
        <Loader2 size={14} className="text-blue-400 animate-spin shrink-0" />
        <Telescope size={13} className="text-muted-foreground shrink-0" />
        <span className="text-sm font-semibold text-foreground">Scout</span>
        <span className="text-xs text-muted-foreground">
          exploring…{toolCount > 0 && ` (${toolCount} ${toolCount === 1 ? "call" : "calls"})`}
        </span>
      </div>
    );
  }

  const toolCount = report.toolCalls.length;
  const elapsed = formatDuration(report.elapsedMs);

  return (
    <div className="flex items-center gap-1.5">
      <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
      <Telescope size={13} className="text-muted-foreground shrink-0" />
      <span className="text-sm font-semibold text-muted-foreground">Scout</span>
      <span className="text-xs text-muted-foreground/70">
        · {toolCount} {toolCount === 1 ? "call" : "calls"} · {elapsed}
      </span>
    </div>
  );
});

/** Level 2: Expanded report card showing tool call summary. */
const ReportCard = memo(function ReportCard({ report }: { report: PreflightReport }) {
  // Aggregate by tool name
  const toolSummary = report.toolCalls.reduce<Record<string, number>>((acc, tc) => {
    acc[tc.toolName] = (acc[tc.toolName] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="ml-3 pl-2 border-l-2 border-border space-y-1.5 py-1.5">
      {/* Tool usage chips */}
      <div className="flex flex-wrap gap-1">
        {Object.entries(toolSummary).map(([name, count]) => (
          <span
            key={name}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-muted/50 text-muted-foreground"
          >
            <Wrench size={10} className="shrink-0" />
            {TOOL_LABELS[name] ?? name}
            {count > 1 && <span className="text-muted-foreground/60">×{count}</span>}
          </span>
        ))}
      </div>
      {/* Stats row */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground/60">
        <span className="flex items-center gap-1">
          <Clock size={10} />
          {formatDuration(report.elapsedMs)}
        </span>
        {report.briefLength > 0 && (
          <span className="flex items-center gap-1">
            <FileText size={10} />
            {report.briefLength.toLocaleString()} chars
          </span>
        )}
      </div>
    </div>
  );
});

/** Level 3: Full exploration log with collapsible tool calls. */
const ExplorationLog = memo(function ExplorationLog({ report }: { report: PreflightReport }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  return (
    <div className="ml-3 pl-2 border-l-2 border-border space-y-0.5 py-1">
      {report.toolCalls.map((tc, i) => {
        const isExpanded = expandedIdx === i;
        const label = TOOL_LABELS[tc.toolName] ?? tc.toolName;
        const duration = tc.durationMs ? formatDuration(tc.durationMs) : null;

        return (
          <div key={i}>
            <button
              onClick={() => setExpandedIdx(isExpanded ? null : i)}
              className="flex items-start gap-1.5 w-full text-left py-1 px-1.5 rounded-sm transition-colors hover:bg-accent/50"
            >
              {isExpanded ? (
                <ChevronDown size={12} className="text-muted-foreground shrink-0 mt-0.5" />
              ) : (
                <ChevronRight size={12} className="text-muted-foreground shrink-0 mt-0.5" />
              )}
              <span className="text-[12px] text-foreground/70 flex-1 truncate">
                {label}
                {tc.toolArgs && (
                  <span className="text-muted-foreground/50 ml-1">
                    ({tc.toolArgs.length > 60 ? tc.toolArgs.slice(0, 60) + "…" : tc.toolArgs})
                  </span>
                )}
              </span>
              {duration && (
                <span className="text-[10px] text-muted-foreground/40 shrink-0">{duration}</span>
              )}
            </button>
            {isExpanded && tc.resultPreview && (
              <div className="ml-5 mb-1.5">
                <pre className="text-[11px] text-muted-foreground/60 bg-muted/30 rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {tc.resultPreview}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});

/** Main ScoutReportCard — integrates all 3 levels. */
export function ScoutReportCard({
  report,
  status,
}: {
  report: PreflightReport | null;
  status: "active" | "done";
}) {
  const [expanded, setExpanded] = useState(false);
  const [showLog, setShowLog] = useState(false);

  return (
    <div>
      {/* Level 1: Clickable header */}
      <button
        onClick={() => report && setExpanded((e) => !e)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left py-1.5 hover:bg-accent/50 rounded-sm transition-colors",
          !report && "cursor-default",
        )}
      >
        {report ? (
          expanded ? (
            <ChevronDown size={13} className="text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight size={13} className="text-muted-foreground shrink-0" />
          )
        ) : (
          <span className="w-[13px]" />
        )}
        <ScoutSummaryLine report={report} status={status} />
      </button>

      {/* Level 2: Report card */}
      {expanded && report && (
        <>
          <ReportCard report={report} />
          {/* Level 3 toggle */}
          {report.toolCalls.length > 0 && (
            <div className="ml-5 mt-1">
              <button
                onClick={() => setShowLog((s) => !s)}
                className="text-[11px] text-primary/70 hover:text-primary transition-colors"
              >
                {showLog ? "Hide exploration log" : "View exploration log"}
              </button>
            </div>
          )}
        </>
      )}

      {/* Level 3: Full exploration log */}
      {expanded && showLog && report && <ExplorationLog report={report} />}
    </div>
  );
}
