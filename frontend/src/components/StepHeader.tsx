import { CheckCircle, ChevronRight, Circle, Loader2 } from "lucide-react";
import { cn } from "../lib/utils";
import type { Step } from "../store";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "just now";
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

interface StepHeaderProps {
  step: Step;
  expanded: boolean;
  onToggle: () => void;
  hideChevron?: boolean;
  /** Whether expand has content to reveal (tool calls, files, agent message) */
  hasExpandableContent?: boolean;
}

export function StepHeader({ step, expanded, onToggle, hideChevron, hasExpandableContent }: StepHeaderProps) {
  const showChevron = !hideChevron && hasExpandableContent;
  const isClickable = hasExpandableContent;

  return (
    <div
      className={cn("flex items-center gap-2 group", isClickable ? "cursor-pointer active:bg-muted/30" : "cursor-default")}
      onClick={isClickable ? onToggle : undefined}
      title={!hideChevron ? (step.summary ?? undefined) : undefined}
    >
      {step.status === "active" ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" />
      ) : step.status === "pending" ? (
        <Circle className="h-4 w-4 shrink-0 text-muted-foreground/40" />
      ) : (
        <CheckCircle className="h-4 w-4 shrink-0 text-emerald-500" />
      )}

      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium truncate block">{step.label}</span>
        {step.summary && (expanded || hideChevron) && (
          <span className="text-xs text-muted-foreground truncate block mt-0.5">{step.summary}</span>
        )}
      </div>

      <span className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
        {step.toolCount > 0 && <span>{step.toolCount} tools</span>}
        {step.durationMs != null && (
          <span className="tabular-nums">{formatDuration(step.durationMs)}</span>
        )}
        {step.startedAt && <span className="tabular-nums">{relativeTime(step.startedAt)}</span>}
      </span>

      {showChevron && (
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-90",
          )}
        />
      )}
    </div>
  );
}
