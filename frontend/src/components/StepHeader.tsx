import { CheckCircle, ChevronRight, Circle, Loader2, XCircle } from "lucide-react";
import { cn } from "../lib/utils";
import type { Step } from "../store";

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
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

  const statusLabel = step.status === "active" ? "Running" : step.status === "pending" ? "Pending" : step.status === "failed" ? "Failed" : "Done";

  return (
    <div
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      aria-expanded={isClickable ? expanded : undefined}
      aria-label={isClickable ? `${step.label}, ${statusLabel}` : undefined}
      className={cn("flex items-center gap-2 group", isClickable ? "cursor-pointer active:bg-muted/30" : "cursor-default")}
      onClick={isClickable ? onToggle : undefined}
      onKeyDown={isClickable ? (e: React.KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); }
      } : undefined}
      title={!hideChevron ? (step.summary ?? undefined) : undefined}
    >
      {step.status === "active" ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" aria-label="Running" />
      ) : step.status === "pending" ? (
        <Circle className="h-4 w-4 shrink-0 text-muted-foreground/40" aria-label="Pending" />
      ) : step.status === "failed" ? (
        <XCircle className="h-4 w-4 shrink-0 text-destructive" aria-label="Failed" />
      ) : (
        <CheckCircle className="h-4 w-4 shrink-0 text-emerald-500" aria-label="Done" />
      )}

      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium truncate block">{step.label}</span>
        {step.summary && (expanded || hideChevron || step.status === "done") && (
          <span className="text-xs text-muted-foreground truncate block mt-0.5">{step.summary}</span>
        )}
      </div>

      <span className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
        {step.toolCount > 0 && <span>{step.toolCount} tools</span>}
        {step.durationMs != null && (
          <span className="tabular-nums">{formatDuration(step.durationMs)}</span>
        )}
      </span>

      {showChevron && (
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-90",
          )}
        />
      )}
    </div>
  );
}
