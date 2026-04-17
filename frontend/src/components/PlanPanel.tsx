import { useState } from "react";
import { ChevronDown, ChevronRight, ListChecks, Circle, CheckCircle2, Loader2 } from "lucide-react";
import { useStore, selectJobPlan } from "../store";
import type { PlanStep } from "../store";
import { cn } from "../lib/utils";

function StepIcon({ status, size = 13 }: { status: PlanStep["status"]; size?: number }) {
  switch (status) {
    case "done":
      return <CheckCircle2 size={size} className="text-emerald-400 shrink-0" />;
    case "active":
      return <Loader2 size={size} className="text-blue-400 animate-spin shrink-0" />;
    default:
      return <Circle size={size} className="text-muted-foreground/40 shrink-0" />;
  }
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
      <div
        className={cn(
          "h-full rounded-full transition-all duration-500 ease-out",
          pct === 100 ? "bg-emerald-400" : "bg-blue-400",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function StepList({ steps, onHover }: { steps: PlanStep[]; onHover: (id: string | null) => void }) {
  // Filter out skipped steps entirely — they add no value to the UI
  const visible = steps.filter((s) => s.status !== "skipped");
  return (
    <div className="space-y-1.5">
      {visible.map((step, i) => (
        <div
          key={step.planStepId ?? i}
          className={cn(
            "flex items-start gap-2 transition-opacity duration-300",
            step.status === "done" && "text-muted-foreground/60",
            step.status === "active" && "text-foreground",
            step.status === "pending" && "text-muted-foreground",
          )}
          onMouseEnter={() => step.planStepId && onHover(step.planStepId)}
          onMouseLeave={() => onHover(null)}
        >
          <div className="mt-0.5">
            <StepIcon status={step.status} />
          </div>
          <div className="flex-1 min-w-0">
            <span className={cn("text-xs leading-snug", step.status === "active" && "font-medium")}>
              {step.label}
            </span>
            {step.status === "done" && step.filesWritten && step.filesWritten.length > 0 && (
              <span className="text-[10px] text-muted-foreground/50 ml-1.5 tabular-nums">
                {step.filesWritten.length} file{step.filesWritten.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Sidebar-embedded plan panel for the activity timeline. */
export function PlanPanel({ jobId }: { jobId: string }) {
  const steps = useStore(selectJobPlan(jobId));
  const setHoveredPlanItemId = useStore((s) => s.setHoveredPlanItemId);
  const [expanded, setExpanded] = useState(true);
  const visible = steps.filter((s) => s.status !== "skipped");

  if (visible.length === 0) return null;

  const doneCount = visible.filter((s) => s.status === "done").length;
  const activeStep = visible.find((s) => s.status === "active");
  const isComplete = !visible.some((s) => s.status === "active" || s.status === "pending");

  return (
    <div className="border-b border-border">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-2 px-3 py-2 w-full text-left hover:bg-accent/50 transition-colors"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-muted-foreground shrink-0" />
        )}
        <ListChecks size={12} className={cn("shrink-0", isComplete ? "text-emerald-400" : "text-muted-foreground")} />
        <span className="text-xs font-semibold text-muted-foreground">Plan</span>
        {!expanded && activeStep && (
          <span className="text-[11px] text-muted-foreground/70 truncate ml-0.5 flex-1 min-w-0">
            — {activeStep.label}
          </span>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground/50 tabular-nums shrink-0">
          {doneCount}/{visible.length}
        </span>
      </button>

      {/* Progress bar — always visible */}
      <div className="px-3 pb-2">
        <ProgressBar done={doneCount} total={visible.length} />
      </div>

      {expanded && (
        <div className="px-3 pb-3 max-h-[200px] overflow-y-auto">
          <StepList steps={visible} onHover={setHoveredPlanItemId} />
        </div>
      )}
    </div>
  );
}

/** Persistent bottom drawer for mobile — shows active step + progress, expandable. */
export function MobilePlanDrawer({ jobId }: { jobId: string }) {
  const steps = useStore(selectJobPlan(jobId));
  const [expanded, setExpanded] = useState(false);
  const visible = steps.filter((s) => s.status !== "skipped");

  if (visible.length === 0) return null;

  const doneCount = visible.filter((s) => s.status === "done").length;
  const activeStep = visible.find((s) => s.status === "active");
  const isComplete = !visible.some((s) => s.status === "active" || s.status === "pending");

  return (
    <div
      className={cn(
        "lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-card border-t border-border shadow-[0_-4px_12px_rgba(0,0,0,0.15)] transition-all duration-300",
        expanded ? "max-h-[50dvh] sm:max-h-[60vh]" : "max-h-14",
      )}
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {/* Collapsed bar — always visible */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-2 px-4 py-3 w-full text-left relative"
      >
        <div className="w-8 h-1 rounded-full bg-muted-foreground/30 absolute top-1.5 left-1/2 -translate-x-1/2" />
        <ListChecks size={14} className={cn("shrink-0", isComplete ? "text-emerald-400" : "text-blue-400")} />
        {activeStep ? (
          <span className="text-xs text-foreground font-medium truncate flex-1 min-w-0">
            {activeStep.label}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground truncate flex-1 min-w-0">
            {isComplete ? "Plan complete" : "Plan"}
          </span>
        )}
        <span className="text-[11px] text-muted-foreground/50 tabular-nums shrink-0">
          {doneCount}/{visible.length}
        </span>
        <div className="w-16 shrink-0">
          <ProgressBar done={doneCount} total={visible.length} />
        </div>
        {expanded ? (
          <ChevronDown size={14} className="text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-muted-foreground shrink-0 -rotate-90" />
        )}
      </button>

      {/* Expanded step list */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 overflow-y-auto max-h-[calc(60vh-3.5rem)]">
          <StepList steps={visible} onHover={() => {}} />
        </div>
      )}
    </div>
  );
}
