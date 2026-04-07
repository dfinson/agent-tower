import { useMemo, useState } from "react";
import { ChevronRight, GitCompareArrows, User } from "lucide-react";
import { cn } from "../lib/utils";
import { useStore, selectStepEntries } from "../store";
import type { Step } from "../store";
import { useIsMobile } from "../hooks/useIsMobile";
import { StepHeader } from "./StepHeader";
import { AgentMarkdown } from "./AgentMarkdown";
import { FilesTouchedChips } from "./FilesTouchedChips";
import { CommandChips } from "./CommandChips";

/* ---------- ToolCallRow (expandable) ---------- */

function ToolCallRow({ entry }: { entry: import("../store").TranscriptEntry }) {
  const [open, setOpen] = useState(false);
  const hasDetail = !!(entry.toolResult || entry.toolArgs);

  return (
    <div>
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        aria-expanded={hasDetail ? open : undefined}
        aria-label={`${entry.toolDisplay || entry.toolName}${entry.toolSuccess === false ? " (failed)" : ""}`}
        className={cn(
          "flex items-center gap-2 w-full text-left text-xs py-1 rounded min-h-[44px] sm:min-h-0",
          hasDetail ? "hover:bg-muted/50 active:bg-muted/50 cursor-pointer" : "cursor-default",
        )}
      >
        {hasDetail && (
          <ChevronRight
            size={12}
            aria-hidden="true"
            className={cn(
              "shrink-0 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
          />
        )}
        {!hasDetail && <span className="w-3 shrink-0" aria-hidden="true" />}
        <span className="shrink-0 mt-px" aria-hidden="true">
          {entry.toolSuccess === false ? "✗" : "✓"}
        </span>
        <span className="font-mono text-foreground/80 truncate flex-1">
          {entry.toolDisplay || entry.toolName}
        </span>
        {entry.toolDurationMs != null && (
          <span className="shrink-0 text-muted-foreground tabular-nums">
            {entry.toolDurationMs < 1000
              ? `${entry.toolDurationMs}ms`
              : `${(entry.toolDurationMs / 1000).toFixed(1)}s`}
          </span>
        )}
      </button>

      {open && (
        <div className="ml-7 mb-2 border-l border-border pl-3">
          {entry.toolArgs && (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer hover:text-foreground select-none py-0.5">
                Arguments
              </summary>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all text-foreground/70 bg-muted/30 rounded p-2">
                {entry.toolArgs}
              </pre>
            </details>
          )}
          {entry.toolResult && (
            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs text-foreground/70 bg-muted/30 rounded p-2">
              {entry.toolResult}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- StepContainer ---------- */

/** Check if a tool is hidden (SDK-internal, never shown). */
function isHiddenTool(entry: import("../store").TranscriptEntry): boolean {
  return entry.toolVisibility === "hidden";
}

/** Check if a tool is collapsed (read-only recon, shown summarised). */
function isCollapsedTool(entry: import("../store").TranscriptEntry): boolean {
  return entry.toolVisibility === "collapsed";
}

interface StepContainerProps {
  step: Step;
  isActive: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  onViewDiff?: (step: Step) => void;
}

export function StepContainer({ step, isActive, expanded: externalExpanded, onToggle: externalToggle, onViewDiff }: StepContainerProps) {
  const isMobile = useIsMobile();
  const [localExpanded, setLocalExpanded] = useState(false);

  const expanded = externalExpanded ?? localExpanded;
  const toggleExpanded = externalToggle ?? (() => setLocalExpanded((v) => !v));

  const stepEntries = useStore(selectStepEntries(step.jobId, step.stepId));

  const currentTool = useMemo(() => {
    if (step.status !== "active") return null;
    const tools = stepEntries.filter((e) => e.role === "tool_running" && !isHiddenTool(e));
    return tools.length > 0 ? tools[tools.length - 1] : null;
  }, [stepEntries, step.status]);

  const agentMessage = useMemo(() => {
    const msgs = stepEntries.filter((e) => e.role === "agent");
    return msgs.length > 0 ? msgs[msgs.length - 1] : null;
  }, [stepEntries]);

  const toolCalls = useMemo(
    () => stepEntries.filter((e) => e.role === "tool_call" && !isHiddenTool(e)),
    [stepEntries],
  );

  const visibleTools = useMemo(
    () => toolCalls.filter((e) => !isCollapsedTool(e)),
    [toolCalls],
  );

  const operatorMessages = useMemo(
    () => stepEntries.filter((e) => e.role === "operator"),
    [stepEntries],
  );

  // Does this step have content worth expanding?
  const hasExpandableContent = toolCalls.length > 0
    || agentMessage != null
    || (step.filesWritten ?? []).length > 0
    || (step.startSha != null && step.endSha != null && step.startSha !== step.endSha);

  // Streaming delta for active step
  const streamingKey = `${step.jobId}:__default__`;
  const streamingText = useStore((s) => s.streamingMessages[streamingKey]);

  const handleToggle = () => {
    if (!hasExpandableContent) return;
    toggleExpanded();
  };

  return (
    <div
      className={cn(
        "border-l-2 pl-4 pr-4 py-3 transition-colors",
        isMobile && "min-h-[44px]",
        isActive
          ? "border-l-blue-500 bg-blue-500/5"
          : step.status === "done"
            ? "border-l-emerald-500/30"
            : step.status === "pending"
              ? "border-l-muted-foreground/20"
              : "border-l-transparent",
      )}
    >
      <StepHeader
        step={step}
        expanded={expanded}
        onToggle={handleToggle}
        hasExpandableContent={hasExpandableContent}
      />

      {/* Running: show latest tool or streaming delta */}
      {isActive && currentTool && (
        <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" aria-hidden="true" />
          <span className="truncate">
            {currentTool.toolIntent || currentTool.toolDisplay || currentTool.toolName}
          </span>
        </div>
      )}

      {isActive && !currentTool && streamingText && (
        <div className="mt-2 text-sm text-foreground/90 leading-relaxed line-clamp-2" aria-live="polite">
          <span>{streamingText}</span>
          <span className="inline-block w-0.5 h-4 bg-foreground/50 animate-pulse ml-0.5" aria-hidden="true" />
        </div>
      )}

      {/* Operator messages — shown inline with chat bubble treatment */}
      {operatorMessages.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {operatorMessages.map((msg) => (
            <div key={msg.seq} className="flex items-start gap-2 justify-end">
              <div className="rounded-lg bg-primary/10 border border-primary/20 px-3 py-1.5 max-w-[85%]">
                <div className="text-xs text-foreground/80 leading-relaxed">
                  <AgentMarkdown content={msg.content} />
                </div>
              </div>
              <div className="shrink-0 w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center mt-0.5">
                <User size={10} className="text-primary" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Expanded: summary + agent message */}
      {expanded && agentMessage && (
        <div className="mt-2 text-sm text-foreground/90 leading-relaxed">
          <AgentMarkdown content={agentMessage.content} />
        </div>
      )}

      {/* File chips — always visible; collapsed for old completed steps */}
      <FilesTouchedChips step={step} collapsed={!isActive && step.status === "done" && !expanded} />

      {/* Terminal command chips — always visible; collapsed for old completed steps */}
      <CommandChips step={step} collapsed={!isActive && step.status === "done" && !expanded} />

      {/* Expanded: visible tool calls (mutations) */}
      {expanded && visibleTools.length > 0 && (
        <div className="mt-3 space-y-0.5 border-t pt-3">
          {visibleTools.map((tc) => (
            <ToolCallRow key={`${tc.seq}-${tc.toolName}`} entry={tc} />
          ))}
        </div>
      )}

      {/* Step diff button — only when SHAs actually differ (real git changes) */}
      {step.startSha && step.endSha && step.startSha !== step.endSha && (
        <button
          onClick={() => onViewDiff?.(step)}
          className="inline-flex items-center gap-1.5 text-xs font-medium mt-2 px-2.5 py-1 rounded border border-border text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        >
          <GitCompareArrows size={12} aria-hidden="true" />
          View changes
        </button>
      )}
    </div>
  );
}
