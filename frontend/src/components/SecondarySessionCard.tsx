/**
 * SecondarySessionCard — inline feed card for secondary sessions.
 *
 * Design:
 * - Header: icon, name, status badge, elapsed time
 * - When running: latest reasoning line (live-updating)
 * - When completed: output always visible (markdown)
 * - Expandable: full turn-based feed (identical to the main chat transcript)
 */

import { useState, useMemo, memo } from "react";
import {
  ChevronDown, ChevronRight, CheckCircle2, Loader2, XCircle,
  Brain, Telescope, Bot, Eye, Sparkles, Wrench, MessageCircle,
  Shield, Zap, Search, FileText, AlertTriangle, Bug,
} from "lucide-react";
import { cn } from "../lib/utils";
import { AgentMarkdown } from "./AgentMarkdown";
import type { SecondarySession, SecondarySessionEntry, TranscriptEntry } from "../store/types";
import { buildFeedItems } from "./CuratedFeedLogic";
import type { FeedItem } from "./CuratedFeedLogic";
import { PhaseBox, SubAgentBubble } from "./CuratedFeedPreviews";

/** Map session kind → icon component. */
const KIND_ICONS: Record<string, typeof Bot> = {
  preflight: Telescope,
  sidecar: Bot,
  monitor: Eye,
  extractor: Sparkles,
};

/** Convert all SecondarySessionEntries to TranscriptEntries for the feed builder. */
function entriesToTranscript(entries: SecondarySessionEntry[]): TranscriptEntry[] {
  return entries.map((entry) => {
    if (entry.kind === "reasoning") {
      return {
        jobId: "",
        seq: entry.seq,
        timestamp: "",
        role: "thinking",
        content: entry.content,
      };
    }
    if (entry.kind === "tool_call") {
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
    if (entry.kind === "output") {
      return {
        jobId: "",
        seq: entry.seq,
        timestamp: "",
        role: "agent",
        content: entry.content,
      };
    }
    // error
    return {
      jobId: "",
      seq: entry.seq,
      timestamp: "",
      role: "agent",
      content: entry.content,
    };
  });
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

/** Mini-feed renderer — uses the same turn/cluster logic as the main chat. */
const MiniFeed = memo(function MiniFeed({ entries }: { entries: SecondarySessionEntry[] }) {
  const feedItems = useMemo(() => {
    const transcript = entriesToTranscript(entries);
    return buildFeedItems(transcript, []);
  }, [entries]);

  return (
    <div className="space-y-1">
      {feedItems.map((item, i) => (
        <MiniFeedItem key={i} item={item} />
      ))}
    </div>
  );
});

/** Render a single feed item — mirrors AgentTurnBlock/CondensedTurnBlock from the main feed. */
function MiniFeedItem({ item }: { item: FeedItem }) {
  if (item.type === "turn" || item.type === "condensed") {
    const { turn, clusters } = item;
    const hasTools = clusters.length > 0;
    const messageContent = turn.message?.content?.trim() ?? "";
    const hasMessage = !!messageContent;
    const hasReasoning = !!turn.reasoning?.content;

    return (
      <div className="py-2 space-y-1.5">
        {hasTools && (
          <div className="space-y-1.5">
            {clusters.map((c, ci) => {
              if (c.kind === "agent") {
                return <SubAgentBubble key={ci} cluster={c} />;
              }
              return (
                <PhaseBox
                  key={ci}
                  cluster={c}
                  defaultExpanded={ci === clusters.length - 1}
                  hasSubsequentActivity={ci < clusters.length - 1 || hasMessage}
                />
              );
            })}
          </div>
        )}

        {(hasMessage || (hasReasoning && !hasTools)) && (
          <div className="min-w-0 rounded-lg bg-card/60 px-2.5 py-2 space-y-1.5">
            {hasReasoning && (
              <div className="text-xs text-foreground/60 leading-snug border-l-2 border-primary/30 pl-2.5">
                <div className="flex items-start gap-1.5">
                  <Brain size={12} className="shrink-0 text-primary/50 mt-0.5" />
                  <p className="whitespace-pre-wrap italic max-h-32 overflow-y-auto">
                    {turn.reasoning!.content}
                  </p>
                </div>
              </div>
            )}
            {hasMessage && (
              <div className="text-[14px] text-foreground leading-relaxed">
                <AgentMarkdown content={messageContent} />
              </div>
            )}
          </div>
        )}

        {hasReasoning && hasTools && !hasMessage && (
          <div className="text-xs text-foreground/60 leading-snug border-l-2 border-primary/30 pl-2.5">
            <div className="flex items-start gap-1.5">
              <Brain size={12} className="shrink-0 text-primary/50 mt-0.5" />
              <p className="whitespace-pre-wrap italic max-h-32 overflow-y-auto">
                {turn.reasoning!.content}
              </p>
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}

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

      {/* Expand toggle */}
      {session.entries.length > 0 && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 mt-1.5 text-[11px] text-primary/60 hover:text-primary transition-colors pl-[22px]"
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          {expanded ? "Collapse" : `Details${toolCalls > 0 ? ` (${toolCalls} ${toolCalls === 1 ? "call" : "calls"})` : ""}`}
        </button>
      )}

      {/* Expanded: full turn-based feed (same rendering as main chat) */}
      {expanded && (
        <div className="mt-2 pl-1">
          <MiniFeed entries={session.entries} />
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
