import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, User, Search, X } from "lucide-react";
import { cn } from "../lib/utils";
import { useStore, selectJobTranscript, selectJobSteps, selectActiveStep } from "../store";
import type { Step, TranscriptEntry } from "../store";
import { AgentMarkdown } from "./AgentMarkdown";
import {
  ToolStepList,
  ReasoningBlock,
  extractReportIntent,
  formatDuration,
} from "./ToolRenderers";

// ---------------------------------------------------------------------------
// Turn grouping — group sequential entries into agent "turns"
// ---------------------------------------------------------------------------

interface AgentTurn {
  key: string;
  stepId: string | null;
  reasoning: TranscriptEntry | null;
  toolCalls: TranscriptEntry[];
  message: TranscriptEntry | null;
  intent: string | null;
  firstTimestamp: string;
}

type FeedItem =
  | { type: "step-divider"; step: Step; key: string }
  | { type: "turn"; turn: AgentTurn; key: string }
  | { type: "operator"; entry: TranscriptEntry; key: string };

function buildTurns(entries: TranscriptEntry[]): AgentTurn[] {
  const turns: AgentTurn[] = [];
  let current: AgentTurn | null = null;

  const flush = () => {
    if (current) {
      current.intent = extractReportIntent(current.toolCalls);
      turns.push(current);
    }
  };

  for (const entry of entries) {
    if (entry.role === "operator" || entry.role === "divider") continue;

    // Start new turn on reasoning or first tool_call/tool_running after a message
    const needsNewTurn = !current
      || (entry.role === "reasoning" && current.reasoning != null)
      || (entry.role === "agent" && current.message != null)
      || (entry.role === "reasoning" && current.toolCalls.length > 0);

    if (needsNewTurn) {
      flush();
      current = {
        key: `turn-${entry.seq}`,
        stepId: entry.stepId ?? null,
        reasoning: null,
        toolCalls: [],
        message: null,
        intent: null,
        firstTimestamp: entry.timestamp,
      };
    }

    if (entry.role === "reasoning") {
      current!.reasoning = entry;
    } else if (entry.role === "tool_call" || entry.role === "tool_running") {
      current!.toolCalls.push(entry);
    } else if (entry.role === "agent") {
      current!.message = entry;
    }
  }
  flush();
  return turns;
}

// ---------------------------------------------------------------------------
// Step progress rail — compact horizontal TOC
// ---------------------------------------------------------------------------

function StepRail({
  steps,
  activeStepId,
  onStepClick,
}: {
  steps: Step[];
  activeStepId: string | null;
  onStepClick: (stepId: string) => void;
}) {
  if (steps.length === 0) return null;
  return (
    <div className="flex items-center gap-1.5 px-4 py-2 border-b border-border overflow-x-auto scrollbar-thin">
      {steps.map((s, i) => {
        const isActive = s.stepId === activeStepId;
        const isDone = s.status === "done";
        const isFailed = s.status === "failed";
        return (
          <button
            key={s.stepId}
            onClick={() => onStepClick(s.stepId)}
            className={cn(
              "flex items-center gap-1 shrink-0 text-[10px] font-medium px-2 py-1 rounded-full transition-colors",
              isActive
                ? "bg-blue-500/15 text-blue-400 ring-1 ring-blue-500/30"
                : isDone
                  ? "bg-emerald-500/10 text-emerald-500/80 hover:bg-emerald-500/20"
                  : isFailed
                    ? "bg-red-500/10 text-red-400/80 hover:bg-red-500/20"
                    : "bg-muted/50 text-muted-foreground/60 hover:bg-muted",
            )}
            title={s.label}
          >
            <span className="tabular-nums">{i + 1}</span>
            <span className="max-w-[80px] truncate hidden sm:inline">{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline search bar
// ---------------------------------------------------------------------------

function InlineSearch({
  query,
  onQueryChange,
}: {
  query: string;
  onQueryChange: (q: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="relative flex items-center px-4 py-1.5 border-b border-border">
      <Search size={13} className="absolute left-6 text-muted-foreground/60" />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Filter activity…"
        className="w-full pl-6 pr-6 py-1 text-xs bg-transparent border-none outline-none text-foreground placeholder:text-muted-foreground/50"
      />
      {query && (
        <button
          onClick={() => { onQueryChange(""); inputRef.current?.focus(); }}
          className="absolute right-6 text-muted-foreground/60 hover:text-foreground"
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepDivider — inline banner where a new step begins
// ---------------------------------------------------------------------------

function StepDivider({
  step,
  index,
  id,
}: {
  step: Step;
  index: number;
  id?: string;
}) {
  const isDone = step.status === "done";
  const isFailed = step.status === "failed";
  const isActive = step.status === "active";
  return (
    <div
      id={id}
      className={cn(
        "flex items-center gap-2 px-4 py-2 text-xs font-medium",
        isActive ? "bg-blue-500/5 text-blue-400"
          : isDone ? "bg-emerald-500/5 text-emerald-500/80"
            : isFailed ? "bg-red-500/5 text-red-400"
              : "bg-muted/30 text-muted-foreground/70",
      )}
    >
      <span className="shrink-0 w-5 h-5 rounded-full flex items-center justify-center border text-[10px] tabular-nums"
        style={{
          borderColor: isActive ? "rgb(59 130 246 / 0.4)" : isDone ? "rgb(16 185 129 / 0.3)" : isFailed ? "rgb(239 68 68 / 0.3)" : "rgb(var(--border) / 0.3)",
        }}
      >
        {index + 1}
      </span>
      <span className="truncate">{step.label}</span>
      {step.durationMs != null && (
        <span className="ml-auto text-muted-foreground/50 shrink-0">{formatDuration(step.durationMs)}</span>
      )}
      {step.summary && <span className="ml-2 text-muted-foreground/40 truncate max-w-[200px]">— {step.summary}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentTurnBlock — renders a single agent turn in the feed
// ---------------------------------------------------------------------------

function AgentTurnBlock({
  turn,
  isActiveTurn,
  streamingText,
}: {
  turn: AgentTurn;
  isActiveTurn: boolean;
  streamingText?: string;
}) {
  const hasTools = turn.toolCalls.length > 0;
  const hasMessage = turn.message != null;

  return (
    <div className="px-4 py-2">
      {/* Intent label if present */}
      {turn.intent && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <Bot size={11} className="text-muted-foreground/50" />
          <span className="text-[11px] text-muted-foreground/70 font-medium">{turn.intent}</span>
        </div>
      )}

      {/* Reasoning */}
      {turn.reasoning && <ReasoningBlock entry={turn.reasoning} />}

      {/* Tool calls — rendered as the rich ToolStepList */}
      {hasTools && (
        <div className="my-1">
          <ToolStepList calls={turn.toolCalls} isActive={isActiveTurn} />
        </div>
      )}

      {/* Agent message */}
      {hasMessage && (
        <div className="text-sm text-foreground/90 leading-relaxed mt-1">
          <AgentMarkdown content={turn.message!.content} />
        </div>
      )}

      {/* Streaming text for active turn */}
      {isActiveTurn && streamingText && !hasMessage && (
        <div className="text-xs text-muted-foreground leading-relaxed line-clamp-3 mt-1">
          <span>{streamingText}</span>
          <span className="inline-block w-0.5 h-3 bg-foreground/40 animate-pulse ml-0.5 align-middle" />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActivityFeed — the main chronological view
// ---------------------------------------------------------------------------

interface ActivityFeedProps {
  jobId: string;
}

export function ActivityFeed({ jobId }: ActivityFeedProps) {
  const allTranscript = useStore(selectJobTranscript(jobId));
  const steps = useStore(selectJobSteps(jobId));
  const activeStep = useStore(selectActiveStep(jobId));
  const streamingKey = `${jobId}:__default__`;
  const streamingText = useStore((s) => s.streamingMessages[streamingKey]);

  const [filterQuery, setFilterQuery] = useState("");

  // Build step index map for quick lookups
  const stepMap = useMemo(() => {
    const m = new Map<string, { step: Step; index: number }>();
    steps.forEach((s, i) => m.set(s.stepId, { step: s, index: i }));
    return m;
  }, [steps]);

  // Build feed items: interleave step dividers with agent turns and operator messages
  const feedItems = useMemo<FeedItem[]>(() => {
    const items: FeedItem[] = [];
    const seenSteps = new Set<string>();
    const turns = buildTurns(allTranscript);

    // Merge turns and operator messages into a single chronological list
    const operatorEntries = allTranscript.filter((e) => e.role === "operator");
    type Mergeable = { ts: string } & (
      | { kind: "turn"; turn: AgentTurn }
      | { kind: "operator"; entry: TranscriptEntry }
    );
    const merged: Mergeable[] = [
      ...turns.map((t) => ({ kind: "turn" as const, turn: t, ts: t.firstTimestamp })),
      ...operatorEntries.map((e) => ({ kind: "operator" as const, entry: e, ts: e.timestamp })),
    ];
    merged.sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime());

    for (const m of merged) {
      if (m.kind === "turn") {
        // Insert step divider before first entry of a new step
        const stepId = m.turn.stepId;
        if (stepId && !seenSteps.has(stepId)) {
          seenSteps.add(stepId);
          const info = stepMap.get(stepId);
          if (info) {
            items.push({ type: "step-divider", step: info.step, key: `div-${stepId}` });
          }
        }
        items.push({ type: "turn", turn: m.turn, key: m.turn.key });
      } else {
        items.push({ type: "operator", entry: m.entry, key: `op-${m.entry.seq}` });
      }
    }

    // Add step dividers for steps that have no transcript yet (pending steps at the end)
    for (const s of steps) {
      if (!seenSteps.has(s.stepId)) {
        items.push({ type: "step-divider", step: s, key: `div-${s.stepId}` });
      }
    }

    return items;
  }, [allTranscript, steps, stepMap]);

  // Client-side filter
  const filteredItems = useMemo(() => {
    if (!filterQuery.trim()) return feedItems;
    const q = filterQuery.toLowerCase();
    return feedItems.filter((item) => {
      if (item.type === "step-divider") return true; // always show step dividers
      if (item.type === "operator") return item.entry.content.toLowerCase().includes(q);
      if (item.type === "turn") {
        const { turn } = item;
        if (turn.message?.content.toLowerCase().includes(q)) return true;
        if (turn.intent?.toLowerCase().includes(q)) return true;
        if (turn.reasoning?.content.toLowerCase().includes(q)) return true;
        for (const tc of turn.toolCalls) {
          if (tc.toolDisplay?.toLowerCase().includes(q)) return true;
          if (tc.toolName?.toLowerCase().includes(q)) return true;
          if (tc.toolIntent?.toLowerCase().includes(q)) return true;
          if (tc.toolArgs?.toLowerCase().includes(q)) return true;
        }
        return false;
      }
      return true;
    });
  }, [feedItems, filterQuery]);

  // Step divider refs for scroll-to-step
  const dividerRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const scrollToStep = useCallback((stepId: string) => {
    const el = dividerRefs.current.get(stepId);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  // Auto-scroll to bottom for new content
  const bottomRef = useRef<HTMLDivElement>(null);
  const [userScrolled, setUserScrolled] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!userScrolled) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [filteredItems.length, userScrolled]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setUserScrolled(!atBottom);
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* Step progress rail */}
      <StepRail
        steps={steps}
        activeStepId={activeStep?.stepId ?? null}
        onStepClick={scrollToStep}
      />

      {/* Inline search */}
      <InlineSearch query={filterQuery} onQueryChange={setFilterQuery} />

      {/* Feed content */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto divide-y divide-border/30"
      >
        {filteredItems.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 px-4">
            <Bot className="h-6 w-6 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">
              {filterQuery ? "No matching activity" : "No activity yet"}
            </p>
          </div>
        )}

        {filteredItems.map((item) => {
          if (item.type === "step-divider") {
            const info = stepMap.get(item.step.stepId);
            return (
              <div
                key={item.key}
                ref={(el) => { if (el) dividerRefs.current.set(item.step.stepId, el); }}
              >
                <StepDivider step={item.step} index={info?.index ?? 0} id={`activity-step-${item.step.stepId}`} />
              </div>
            );
          }
          if (item.type === "operator") {
            return (
              <div key={item.key} className="px-4 py-2">
                <div className="flex items-start gap-2 justify-end">
                  <div className="rounded-lg bg-primary/10 border border-primary/20 px-3 py-1.5 max-w-[85%]">
                    <div className="text-xs text-foreground/80 leading-relaxed">
                      <AgentMarkdown content={item.entry.content} />
                    </div>
                  </div>
                  <div className="shrink-0 w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center mt-0.5">
                    <User size={10} className="text-primary" />
                  </div>
                </div>
              </div>
            );
          }
          if (item.type === "turn") {
            const turnsForStep = filteredItems.filter((f): f is FeedItem & { type: "turn" } => f.type === "turn" && f.turn.stepId === activeStep?.stepId);
            const isActiveTurn = item.turn.stepId === activeStep?.stepId
              && turnsForStep.length > 0 && item === turnsForStep[turnsForStep.length - 1];
            return (
              <AgentTurnBlock
                key={item.key}
                turn={item.turn}
                isActiveTurn={!!isActiveTurn}
                streamingText={streamingText}
              />
            );
          }
          return null;
        })}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
