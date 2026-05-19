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
  Wrench, Brain, Telescope, Bot, Eye, Sparkles, MessageCircle,
  Shield, Zap, Search, FileText, AlertTriangle, Bug,
} from "lucide-react";
import { cn } from "../lib/utils";
import { AgentMarkdown } from "./AgentMarkdown";
import { ToolStep } from "./ToolRenderers";
import type { SecondarySession, SecondarySessionEntry, TranscriptEntry } from "../store/types";

/** Map session kind → icon component. */
const KIND_ICONS: Record<string, typeof Bot> = {
  preflight: Telescope,
  sidecar: Bot,
  monitor: Eye,
  extractor: Sparkles,
};

/** Format tool args for human-readable display instead of raw JSON. */
function formatToolArgs(toolName: string | null | undefined, rawArgs: string | null | undefined): string | null {
  if (!rawArgs) return null;
  try {
    const args = JSON.parse(rawArgs);
    if (toolName === "view" || toolName === "Read") {
      const path = args.path || args.file_path || "";
      const short = path.split("/").slice(-2).join("/");
      if (args.view_range) return `${short}:${args.view_range[0]}-${args.view_range[1]}`;
      return short;
    }
    if (toolName === "bash" || toolName === "execute") {
      const cmd = args.command || args.cmd || "";
      return cmd.length > 80 ? cmd.slice(0, 77) + "…" : cmd;
    }
    if (toolName === "grep" || toolName === "search") {
      const pattern = args.pattern || args.query || args.regex || "";
      const path = args.path || args.include || "";
      const short = path ? path.split("/").slice(-2).join("/") : "";
      return short ? `"${pattern}" in ${short}` : `"${pattern}"`;
    }
    if (toolName === "write" || toolName === "Edit") {
      const path = args.path || args.file_path || "";
      return path.split("/").slice(-2).join("/");
    }
    // Fallback: show key=value pairs compactly
    const pairs = Object.entries(args)
      .map(([k, v]) => {
        const val = typeof v === "string" ? v : JSON.stringify(v);
        const short = (val as string).length > 30 ? (val as string).slice(0, 27) + "…" : val;
        return `${k}=${short}`;
      })
      .join(" ");
    return pairs.length > 80 ? pairs.slice(0, 77) + "…" : pairs;
  } catch {
    // Not JSON — return truncated raw string
    return rawArgs.length > 60 ? rawArgs.slice(0, 57) + "…" : rawArgs;
  }
}

/** Map a SecondarySessionEntry (tool_call) to the TranscriptEntry shape used by ToolStep. */
function toTranscriptEntry(entry: SecondarySessionEntry): TranscriptEntry {
  return {
    jobId: "",
    seq: entry.seq,
    timestamp: "",
    role: "tool_call",
    content: entry.content,
    toolName: entry.toolName ?? undefined,
    toolArgs: entry.toolArgs ?? undefined,
    toolResult: entry.toolResult ?? undefined,
    toolDisplay: entry.toolDisplay ?? undefined,
    toolDisplayFull: entry.toolDisplayFull ?? undefined,
    toolSuccess: entry.toolSuccess ?? undefined,
    toolIssue: entry.toolIssue ?? undefined,
    toolVisibility: entry.toolVisibility ?? undefined,
    toolDurationMs: entry.durationMs ?? undefined,
  };
}

/** Map backend icon name → lucide component (used when session.icon is set). */
const ICON_MAP: Record<string, typeof Bot> = {
  bot: Bot,
  telescope: Telescope,
  eye: Eye,
  sparkles: Sparkles,
  wrench: Wrench,
  "message-circle": MessageCircle,
  shield: Shield,
  zap: Zap,
  search: Search,
  "file-text": FileText,
  "alert-triangle": AlertTriangle,
  bug: Bug,
  brain: Brain,
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
          return (
            <div key={i} className="py-0.5">
              <ToolStep entry={toTranscriptEntry(entry)} isActive={false} />
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

/** Compact scouting summary for preflight sessions — shows examined files inline. */
const PreflightScoutingSummary = memo(function PreflightScoutingSummary({
  entries,
}: {
  entries: SecondarySessionEntry[];
}) {
  const examined = entries
    .filter((e) => e.kind === "tool_call")
    .map((e) => {
      const label = formatToolArgs(e.toolName, e.toolArgs);
      return { tool: e.toolName ?? "tool", label, duration: e.durationMs };
    });

  if (examined.length === 0) return null;

  return (
    <div className="mt-1.5 pl-[22px]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[11px] text-muted-foreground/60 uppercase tracking-wide font-medium">Examined</span>
        {examined.map((item, i) => (
          <span key={i} className="inline-flex items-center gap-1 text-[12px] text-foreground/60 bg-muted/40 rounded px-1.5 py-0.5">
            <FileText size={10} className="text-muted-foreground/50" />
            <span className="font-mono text-[11px]">{item.label || item.tool}</span>
          </span>
        ))}
      </div>
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
  const Icon = ICON_MAP[session.icon] ?? KIND_ICONS[session.kind] ?? Bot;
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

  // Detect if output duplicates the last reasoning (avoid showing same text twice)
  const outputDuplicatesReasoning = !!(
    session.output && latestReasoning?.content &&
    session.output.trim() === latestReasoning.content.trim()
  );

  return (
    <div className={cn(
      "rounded-lg border px-3 py-2.5 my-2",
      isRunning && "border-blue-500/30 bg-blue-500/[0.04]",
      isCompleted && session.kind === "preflight" && "border-purple-500/20 bg-purple-500/[0.03]",
      isCompleted && session.kind !== "preflight" && "border-border bg-muted/20",
      isFailed && "border-red-500/30 bg-red-500/[0.04]",
    )}>
      {/* Header row */}
      <div className="flex items-center gap-2">
        <Icon size={14} className={cn(
          "shrink-0",
          isRunning && "text-blue-400",
          isCompleted && session.kind === "preflight" && "text-purple-400/80",
          isCompleted && session.kind !== "preflight" && "text-muted-foreground",
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

      {/* Latest reasoning preview (when collapsed & not duplicating the output) */}
      {!expanded && latestReasoning && !outputDuplicatesReasoning && (
        <p className="text-[12px] text-muted-foreground/60 mt-1.5 line-clamp-1 leading-relaxed pl-[22px]">
          {latestReasoning.content}
        </p>
      )}

      {/* Preflight: show compact scouting summary instead of generic expand */}
      {session.kind === "preflight" && !expanded && toolCalls > 0 && (
        <PreflightScoutingSummary entries={session.entries} />
      )}

      {/* Expand toggle */}
      {session.entries.length > 0 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 mt-1.5 text-[11px] text-primary/60 hover:text-primary transition-colors pl-[22px]"
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          {expanded ? "Collapse" : session.kind === "preflight" ? "Details" : `Expand${toolCalls > 0 ? ` (${toolCalls} ${toolCalls === 1 ? "call" : "calls"})` : ""}`}
        </button>
      )}

      {/* Expanded: full entry timeline */}
      {expanded && (
        <div className="mt-1.5 pl-[22px] border-l-2 border-border/50 ml-[6px]">
          <EntryTimeline entries={session.entries} />
        </div>
      )}

      {/* Output — always visible when completed (skip if expanded and duplicates reasoning) */}
      {isCompleted && session.output && !(expanded && outputDuplicatesReasoning) && (
        <div className="mt-2 pt-2 border-t border-border/50 pl-[22px]">
          <div className="text-[13px] text-foreground/80 leading-relaxed max-h-48 overflow-y-auto">
            <AgentMarkdown content={session.output} />
          </div>
        </div>
      )}
    </div>
  );
});
