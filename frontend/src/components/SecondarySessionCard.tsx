/**
 * SecondarySessionCard — inline feed card for secondary sessions.
 *
 * Design:
 * - Header: icon, name, status badge, elapsed time
 * - When running: latest reasoning line (live-updating)
 * - When completed: output always visible (markdown)
 * - Expandable: full interleaved entry timeline (reasoning → tool_call → ...)
 */

import { useState, useMemo, memo } from "react";
import {
  ChevronDown, ChevronRight, CheckCircle2, Loader2, XCircle,
  Wrench, Brain, Telescope, Bot, Eye, Sparkles,
} from "lucide-react";
import { cn } from "../lib/utils";
import { AgentMarkdown } from "./AgentMarkdown";
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
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

function elapsedSince(startedAt: string, completedAt?: string | null): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  return formatDuration(end - start);
}

/** The interleaved entry timeline (the expandable part). */
const EntryTimeline = memo(function EntryTimeline({ entries }: { entries: SecondarySessionEntry[] }) {
  return (
    <div className="space-y-0.5 py-1.5">
      {entries.map((entry, i) => {
        if (entry.kind === "reasoning") {
          return (
            <div key={i} className="flex items-start gap-2 py-0.5">
              <Brain size={11} className="text-muted-foreground/50 shrink-0 mt-0.5" />
              <p className="text-[12px] text-muted-foreground/80 whitespace-pre-wrap leading-relaxed">
                {entry.content}
              </p>
            </div>
          );
        }

        if (entry.kind === "tool_call") {
          const name = entry.toolName ?? "tool";
          const args = entry.toolArgs
            ? entry.toolArgs.length > 80 ? entry.toolArgs.slice(0, 80) + "…" : entry.toolArgs
            : null;
          const duration = entry.durationMs ? formatDuration(entry.durationMs) : null;

          return (
            <div key={i} className="flex items-start gap-2 py-0.5">
              <Wrench size={11} className="text-blue-400/70 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <span className="text-[12px] font-mono text-foreground/70">{name}</span>
                {args && (
                  <span className="text-[11px] text-muted-foreground/50 ml-1.5">
                    {args}
                  </span>
                )}
              </div>
              {duration && (
                <span className="text-[10px] text-muted-foreground/40 shrink-0 tabular-nums">{duration}</span>
              )}
            </div>
          );
        }

        if (entry.kind === "output") {
          return (
            <div key={i} className="flex items-start gap-2 py-0.5">
              <CheckCircle2 size={11} className="text-emerald-400/70 shrink-0 mt-0.5" />
              <p className="text-[12px] text-muted-foreground whitespace-pre-wrap leading-relaxed line-clamp-4">
                {entry.content}
              </p>
            </div>
          );
        }

        if (entry.kind === "error") {
          return (
            <div key={i} className="flex items-start gap-2 py-0.5">
              <XCircle size={11} className="text-red-400/70 shrink-0 mt-0.5" />
              <p className="text-[12px] text-red-400/80 whitespace-pre-wrap">{entry.content}</p>
            </div>
          );
        }

        return null;
      })}
    </div>
  );
});

/** Main SecondarySessionCard — inline feed block. */
export const SecondarySessionCard = memo(function SecondarySessionCard({
  session,
}: {
  session: SecondarySession;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon = KIND_ICONS[session.kind] ?? Bot;
  const toolCalls = session.entries.filter((e) => e.kind === "tool_call").length;
  const isRunning = session.status === "running";
  const isCompleted = session.status === "completed";
  const isFailed = session.status === "failed" || session.status === "timeout";

  // Latest reasoning line for live preview when collapsed
  const latestReasoning = useMemo(() => {
    for (let i = session.entries.length - 1; i >= 0; i--) {
      if (session.entries[i]!.kind === "reasoning") return session.entries[i]!;
    }
    return undefined;
  }, [session.entries]);

  return (
    <div className={cn(
      "rounded-lg border px-3 py-2.5 my-2",
      isRunning && "border-blue-500/30 bg-blue-500/[0.04]",
      isCompleted && "border-border bg-muted/20",
      isFailed && "border-red-500/30 bg-red-500/[0.04]",
    )}>
      {/* Header row */}
      <div className="flex items-center gap-2">
        <Icon size={14} className={cn(
          "shrink-0",
          isRunning && "text-blue-400",
          isCompleted && "text-muted-foreground",
          isFailed && "text-red-400",
        )} />
        <span className={cn(
          "text-sm font-medium flex-1 min-w-0 truncate",
          isRunning && "text-foreground",
          isCompleted && "text-muted-foreground",
          isFailed && "text-red-400",
        )}>
          {session.name}
        </span>

        {/* Status badge */}
        {isRunning && (
          <span className="flex items-center gap-1 text-[11px] text-blue-400">
            <Loader2 size={11} className="animate-spin" />
            running
          </span>
        )}
        {isCompleted && (
          <span className="flex items-center gap-1 text-[11px] text-emerald-400/80">
            <CheckCircle2 size={11} />
            done
          </span>
        )}
        {isFailed && (
          <span className="flex items-center gap-1 text-[11px] text-red-400/80">
            <XCircle size={11} />
            {session.status}
          </span>
        )}

        {/* Elapsed time */}
        <span className="text-[11px] text-muted-foreground/50 tabular-nums shrink-0">
          {elapsedSince(session.startedAt, session.completedAt)}
        </span>
      </div>

      {/* Latest reasoning preview (when collapsed & has reasoning) */}
      {!expanded && latestReasoning && (
        <p className="text-[12px] text-muted-foreground/60 mt-1.5 line-clamp-1 leading-relaxed pl-[22px]">
          {latestReasoning.content}
        </p>
      )}

      {/* Expand toggle */}
      {session.entries.length > 0 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 mt-1.5 text-[11px] text-primary/60 hover:text-primary transition-colors pl-[22px]"
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          {expanded ? "Collapse" : `Expand${toolCalls > 0 ? ` (${toolCalls} ${toolCalls === 1 ? "call" : "calls"})` : ""}`}
        </button>
      )}

      {/* Expanded: full entry timeline */}
      {expanded && (
        <div className="mt-1.5 pl-[22px] border-l-2 border-border/50 ml-[6px]">
          <EntryTimeline entries={session.entries} />
        </div>
      )}

      {/* Output — always visible when completed */}
      {isCompleted && session.output && (
        <div className="mt-2 pt-2 border-t border-border/50 pl-[22px]">
          <div className="text-[13px] text-foreground/80 leading-relaxed max-h-48 overflow-y-auto">
            <AgentMarkdown content={session.output} />
          </div>
        </div>
      )}
    </div>
  );
});
