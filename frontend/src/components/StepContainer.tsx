import { useMemo, useState } from "react";
import { cn } from "../lib/utils";
import { useStore, selectStepEntries } from "../store";
import type { Step } from "../store";
import { useIsMobile } from "../hooks/useIsMobile";
import { StepHeader } from "./StepHeader";

interface StepContainerProps {
  step: Step;
  isActive: boolean;
}

export function StepContainer({ step, isActive }: StepContainerProps) {
  const isMobile = useIsMobile();
  const [expanded, setExpanded] = useState(false);

  const stepEntries = useStore(selectStepEntries(step.jobId, step.stepId));

  const currentTool = useMemo(() => {
    if (step.status !== "running") return null;
    const tools = stepEntries.filter((e) => e.role === "tool_running");
    return tools.length > 0 ? tools[tools.length - 1] : null;
  }, [stepEntries, step.status]);

  const agentMessage = useMemo(() => {
    const msgs = stepEntries.filter((e) => e.role === "agent");
    return msgs.length > 0 ? msgs[msgs.length - 1] : null;
  }, [stepEntries]);

  const toolCalls = useMemo(
    () => stepEntries.filter((e) => e.role === "tool_call"),
    [stepEntries],
  );

  // Streaming delta for active step
  const streamingKey = step.turnId
    ? `${step.jobId}:${step.turnId}`
    : `${step.jobId}:__default__`;
  const streamingText = useStore((s) => s.streamingMessages[streamingKey]);

  return (
    <div
      className={cn(
        "border-l-2 pl-4 py-3 transition-colors",
        isMobile && "min-h-[44px]",
        isActive
          ? "border-blue-500"
          : step.status === "completed"
            ? "border-emerald-500/30"
            : "border-border",
      )}
    >
      <StepHeader
        step={step}
        expanded={expanded}
        onToggle={() => setExpanded((v) => !v)}
        hideChevron={isMobile}
      />

      {/* Running: show latest tool or streaming delta */}
      {isActive && currentTool && (
        <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="truncate">
            {currentTool.toolIntent || currentTool.toolDisplay || currentTool.toolName}
          </span>
        </div>
      )}

      {isActive && !currentTool && streamingText && (
        <div className="mt-2 text-sm text-foreground/90 leading-relaxed line-clamp-2">
          <span>{streamingText}</span>
          <span className="inline-block w-0.5 h-4 bg-foreground/50 animate-pulse ml-0.5" />
        </div>
      )}

      {/* Completed: show agent summary */}
      {agentMessage && step.status !== "running" && (
        <div
          className={cn(
            "mt-2 text-sm text-foreground/90 leading-relaxed",
            isMobile ? "line-clamp-2" : "line-clamp-3",
          )}
        >
          {agentMessage.content}
        </div>
      )}

      {/* Expanded: tool call list */}
      {!isMobile && expanded && toolCalls.length > 0 && (
        <div className="mt-3 space-y-1 border-t pt-3">
          {toolCalls.map((tc) => (
            <div
              key={`${tc.seq}-${tc.toolName}`}
              className="flex items-start gap-2 text-xs text-muted-foreground"
            >
              <span className="shrink-0 mt-0.5">
                {tc.toolSuccess === false ? "✗" : "✓"}
              </span>
              <span className="font-mono text-foreground/80 truncate flex-1">
                {tc.toolDisplay || tc.toolName}
              </span>
              {tc.toolDurationMs != null && (
                <span className="shrink-0">
                  {tc.toolDurationMs < 1000
                    ? `${tc.toolDurationMs}ms`
                    : `${(tc.toolDurationMs / 1000).toFixed(1)}s`}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
