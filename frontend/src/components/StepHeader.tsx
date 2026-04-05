import { CheckCircle, ChevronRight, Loader2, XCircle } from "lucide-react";
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
}

export function StepHeader({ step, expanded, onToggle, hideChevron }: StepHeaderProps) {
  const displayTitle = step.title || step.intent;

  return (
    <div
      className="flex items-center gap-2 cursor-pointer group"
      onClick={onToggle}
    >
      {step.status === "running" ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-500" />
      ) : step.status === "completed" ? (
        <CheckCircle className="h-4 w-4 shrink-0 text-emerald-500" />
      ) : (
        <XCircle className="h-4 w-4 shrink-0 text-destructive" />
      )}

      <span className="text-sm font-medium truncate flex-1">{displayTitle}</span>

      <span className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
        {step.toolCount > 0 && <span>{step.toolCount} tools</span>}
        {step.durationMs != null && (
          <span className="tabular-nums">{formatDuration(step.durationMs)}</span>
        )}
        <span className="tabular-nums">{relativeTime(step.startedAt)}</span>
      </span>

      {!hideChevron && (
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
