import { useState } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, Loader2, Circle, ListTree } from "lucide-react";
import { useStore, selectActivityTimeline, selectJobPlan } from "../store";
import type { ActivityTimelineActivity, PlanStep } from "../store";
import { cn } from "../lib/utils";

function ActivityStatusIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 size={13} className="text-emerald-400 shrink-0" />;
  if (status === "active") return <Loader2 size={13} className="text-blue-400 animate-spin shrink-0" />;
  return <Circle size={13} className="text-muted-foreground/60 shrink-0" />;
}

function StepDot({ active }: { active: boolean }) {
  return (
    <span
      className={cn(
        "w-2 h-2 rounded-full shrink-0 mt-[5px]",
        active ? "bg-blue-400" : "bg-muted-foreground/70",
      )}
    />
  );
}

function ActivitySection({
  activity,
  isLast,
  selectedTurnId,
  onStepClick,
}: {
  activity: ActivityTimelineActivity;
  isLast: boolean;
  selectedTurnId: string | null;
  onStepClick: (turnId: string) => void;
}) {
  const [expanded, setExpanded] = useState(activity.status === "active");

  return (
    <div>
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-1.5 w-full text-left py-1.5 hover:bg-accent/50 rounded-sm transition-colors group"
      >
        {expanded ? (
          <ChevronDown size={12} className="text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight size={12} className="text-muted-foreground shrink-0" />
        )}
        <span
          className={cn(
            "text-xs font-semibold leading-snug truncate flex-1",
            activity.status === "active" ? "text-foreground" : "text-muted-foreground",
          )}
          title={activity.label}
        >
          {activity.label}
        </span>
        <ActivityStatusIcon status={activity.status} />
      </button>
      {expanded && (
        <div className="ml-3 pl-2 border-l-2 border-border space-y-0.5 pb-1">
          {activity.steps.map((step, i) => {
            const isActive = isLast && i === activity.steps.length - 1 && activity.status === "active";
            const isSelected = selectedTurnId === step.turnId;
            return (
              <button
                key={step.turnId}
                onClick={() => onStepClick(step.turnId)}
                className={cn(
                  "flex items-start gap-1.5 w-full text-left py-1 px-1.5 rounded-sm transition-colors hover:bg-accent/50",
                  isSelected && "bg-accent/60 ring-1 ring-accent",
                )}
              >
                <StepDot active={isActive} />
                <span
                  className={cn(
                    "text-[11px] leading-snug",
                    isActive ? "text-foreground font-medium" : "text-foreground/70",
                  )}
                  title={step.title}
                >
                  {step.title}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PlanSummary({ steps }: { steps: PlanStep[] }) {
  const doneCount = steps.filter((s) => s.status === "done").length;
  if (steps.length === 0) return null;
  return (
    <div className="mt-2 pt-2 border-t border-border">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <span>Plan</span>
        <span className="tabular-nums">{doneCount}/{steps.length}</span>
      </div>
    </div>
  );
}

export function ActivityTimeline({
  jobId,
  onStepClick,
  selectedTurnId,
}: {
  jobId: string;
  onStepClick: (turnId: string) => void;
  selectedTurnId?: string | null;
}) {
  const timeline = useStore(selectActivityTimeline(jobId));
  const planSteps = useStore(selectJobPlan(jobId));
  const hasActiveWork = planSteps.some((s) => s.status === "active" || s.status === "pending");

  if (timeline.activities.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 px-4 py-6">
        <ListTree size={20} className="text-muted-foreground" />
        <span className="text-xs text-muted-foreground text-center leading-relaxed">Activity will appear here as the agent works</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {timeline.activities.map((activity, i) => (
          <ActivitySection
            key={activity.activityId}
            activity={activity}
            isLast={i === timeline.activities.length - 1}
            selectedTurnId={selectedTurnId ?? null}
            onStepClick={onStepClick}
          />
        ))}
      </div>
      {hasActiveWork && <PlanSummary steps={planSteps} />}
    </div>
  );
}
