/**
 * SecondarySessionCard — 3-level progressive disclosure of any secondary session.
 *
 * Level 1: One-line summary (name, status, entry count)
 * Level 2: Expanded card with entry list (reasoning + tool calls)
 * Level 3: Full detail with collapsible tool call results
 */

import { useState, memo } from "react";
import {
  ChevronDown, ChevronRight, CheckCircle2, Loader2, XCircle,
  Wrench, Clock, Telescope, Bot, Eye, Sparkles,
} from "lucide-react";
import { cn } from "../lib/utils";
import type { SecondarySession, SecondarySessionEntry } from "../store/types";

/** Map session kind → icon component. */
const KIND_ICONS: Record<string, typeof Bot> = {
  preflight: Telescope,
  sidecar: Bot,
  monitor: Eye,
  extractor: Sparkles,
};

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Level 1: Compact summary header. */
const SessionSummaryLine = memo(function SessionSummaryLine({
  session,
}: {
  session: SecondarySession;
}) {
  const Icon = KIND_ICONS[session.kind] ?? Bot;
  const entryCount = session.entries.length;
  const toolCalls = session.entries.filter((e) => e.kind === "tool_call").length;

  if (session.status === "running") {
    return (
      <div className="flex items-center gap-1.5">
        <Loader2 size={14} className="text-blue-400 animate-spin shrink-0" />
        <Icon size={13} className="text-muted-foreground shrink-0" />
        <span className="text-sm font-semibold text-foreground">{session.name}</span>
        <span className="text-xs text-muted-foreground">
          working…{toolCalls > 0 && ` (${toolCalls} ${toolCalls === 1 ? "call" : "calls"})`}
        </span>
      </div>
    );
  }

  const statusIcon = session.status === "completed" ? (
    <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
  ) : (
    <XCircle size={14} className="text-red-400 shrink-0" />
  );

  return (
    <div className="flex items-center gap-1.5">
      {statusIcon}
      <Icon size={13} className="text-muted-foreground shrink-0" />
      <span className="text-sm font-semibold text-muted-foreground">{session.name}</span>
      <span className="text-xs text-muted-foreground/70">
        {toolCalls > 0 ? `· ${toolCalls} ${toolCalls === 1 ? "call" : "calls"}` : entryCount === 0 && session.output ? "· message" : ""}
      </span>
    </div>
  );
});

/** Level 2: Entry list with reasoning and tool call chips. */
const EntryList = memo(function EntryList({ entries }: { entries: SecondarySessionEntry[] }) {
  const toolCalls = entries.filter((e) => e.kind === "tool_call");

  if (toolCalls.length === 0 && entries.length === 0) return null;

  // Aggregate tool calls by name
  const toolSummary = toolCalls.reduce<Record<string, number>>((acc, e) => {
    const name = e.toolName ?? "unknown";
    acc[name] = (acc[name] ?? 0) + 1;
    return acc;
  }, {});

  const totalDuration = toolCalls.reduce((sum, e) => sum + (e.durationMs ?? 0), 0);

  return (
    <div className="ml-3 pl-2 border-l-2 border-border space-y-1.5 py-1.5">
      {Object.keys(toolSummary).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(toolSummary).map(([name, count]) => (
            <span
              key={name}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-muted/50 text-muted-foreground"
            >
              <Wrench size={10} className="shrink-0" />
              {name}
              {count > 1 && <span className="text-muted-foreground/60">×{count}</span>}
            </span>
          ))}
        </div>
      )}
      {totalDuration > 0 && (
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground/60">
          <span className="flex items-center gap-1">
            <Clock size={10} />
            {formatDuration(totalDuration)}
          </span>
        </div>
      )}
    </div>
  );
});

/** Level 3: Full log with collapsible entries. */
const DetailLog = memo(function DetailLog({ entries }: { entries: SecondarySessionEntry[] }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  return (
    <div className="ml-3 pl-2 border-l-2 border-border space-y-0.5 py-1">
      {entries.map((entry, i) => {
        const isExpanded = expandedIdx === i;
        const duration = entry.durationMs ? formatDuration(entry.durationMs) : null;

        if (entry.kind === "reasoning") {
          return (
            <div key={i} className="py-0.5 px-1.5">
              <p className="text-[11px] text-muted-foreground/70 whitespace-pre-wrap line-clamp-3">
                {entry.content}
              </p>
            </div>
          );
        }

        const label = entry.toolName ?? entry.kind;
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
                {entry.toolArgs && (
                  <span className="text-muted-foreground/50 ml-1">
                    ({entry.toolArgs.length > 60 ? entry.toolArgs.slice(0, 60) + "…" : entry.toolArgs})
                  </span>
                )}
              </span>
              {duration && (
                <span className="text-[10px] text-muted-foreground/40 shrink-0">{duration}</span>
              )}
            </button>
            {isExpanded && entry.content && (
              <div className="ml-5 mb-1.5">
                <pre className="text-[11px] text-muted-foreground/60 bg-muted/30 rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {entry.content}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});

/** Main SecondarySessionCard — integrates all 3 levels. */
export function SecondarySessionCard({ session }: { session: SecondarySession }) {
  const [expanded, setExpanded] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const hasEntries = session.entries.length > 0;
  const hasContent = hasEntries || !!session.output;

  return (
    <div>
      {/* Level 1: Clickable header */}
      <button
        onClick={() => hasContent && setExpanded((e) => !e)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left py-1.5 hover:bg-accent/50 rounded-sm transition-colors",
          !hasContent && "cursor-default",
        )}
      >
        {hasContent ? (
          expanded ? (
            <ChevronDown size={13} className="text-muted-foreground shrink-0" />
          ) : (
            <ChevronRight size={13} className="text-muted-foreground shrink-0" />
          )
        ) : (
          <span className="w-[13px]" />
        )}
        <SessionSummaryLine session={session} />
      </button>

      {/* Level 2: Entry summary or output fallback */}
      {expanded && hasEntries && (
        <>
          <EntryList entries={session.entries} />
          {/* Level 3 toggle */}
          {session.entries.length > 0 && (
            <div className="ml-5 mt-1">
              <button
                onClick={() => setShowLog((s) => !s)}
                className="text-[11px] text-primary/70 hover:text-primary transition-colors"
              >
                {showLog ? "Hide detail log" : "View detail log"}
              </button>
            </div>
          )}
        </>
      )}
      {expanded && !hasEntries && session.output && (
        <div className="ml-5 pl-2 border-l-2 border-border py-1.5">
          <p className="text-[12px] text-muted-foreground whitespace-pre-wrap line-clamp-6">
            {session.output}
          </p>
        </div>
      )}

      {/* Level 3: Full detail log */}
      {expanded && showLog && <DetailLog entries={session.entries} />}
    </div>
  );
}
