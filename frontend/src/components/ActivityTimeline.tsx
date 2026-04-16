import { useState, useEffect, useRef } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, Loader2, Circle, ListTree } from "lucide-react";
import { useStore, selectActivityTimeline, selectJobPlan, selectHoveredPlanItemId } from "../store";
import type { ActivityTimelineActivity } from "../store";
import { PlanPanel } from "./PlanPanel";
import { cn } from "../lib/utils";

/** Terminal job states where the agent is no longer working. */
const TERMINAL_STATES = new Set([
  "review", "completed", "failed", "canceled", "archived",
]);

function ActivityStatusIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />;
  if (status === "active") return <Loader2 size={14} className="text-blue-400 animate-spin shrink-0" />;
  return <Circle size={14} className="text-muted-foreground/60 shrink-0" />;
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

/** Renders a single step with a brief flash when its title is updated (merge). */
function StepButton({
  step,
  isActive,
  isSelected,
  searchActive,
  onStepClick,
}: {
  step: { turnId: string; title: string };
  isActive: boolean;
  isSelected: boolean;
  searchActive?: boolean;
  onStepClick: (turnId: string) => void;
}) {
  const prevTitle = useRef(step.title);
  const [updated, setUpdated] = useState(false);

  useEffect(() => {
    if (prevTitle.current !== step.title) {
      prevTitle.current = step.title;
      setUpdated(true);
      const timer = setTimeout(() => setUpdated(false), 1200);
      return () => clearTimeout(timer);
    }
  }, [step.title]);

  return (
    <button
      ref={isSelected && searchActive ? (el) => el?.scrollIntoView({ block: "nearest", behavior: "smooth" }) : undefined}
      onClick={() => onStepClick(step.turnId)}
      className={cn(
        "flex items-start gap-1.5 w-full text-left py-2 px-2 rounded-sm transition-colors hover:bg-accent/50",
        isSelected && "bg-primary/10 ring-1 ring-primary/50",
        updated && "animate-step-title-update",
      )}
    >
      <StepDot active={isActive} />
      <span
        className={cn(
          "text-[13px] leading-snug transition-opacity duration-300",
          isActive ? "text-foreground font-medium" : "text-foreground/70",
          updated && "text-blue-400",
        )}
        title={step.title}
      >
        {step.title}
      </span>
    </button>
  );
}

function ActivitySection({
  activity,
  isLast,
  selectedTurnId,
  onStepClick,
  searchActive,
  highlightPlanItemId,
}: {
  activity: ActivityTimelineActivity;
  isLast: boolean;
  selectedTurnId: string | null;
  onStepClick: (turnId: string) => void;
  searchActive?: boolean;
  highlightPlanItemId?: string | null;
}) {
  const [expanded, setExpanded] = useState(activity.status === "active");

  // Highlight when the hovered plan item matches this activity's plan link
  const isLinkedToHoveredPlan = !!highlightPlanItemId && activity.planItemId === highlightPlanItemId;

  // When search is driving the sidebar, auto-expand the activity containing
  // the matched step and collapse everything else.
  const containsSelected = !!selectedTurnId && activity.steps.some((s) => s.turnId === selectedTurnId);
  useEffect(() => {
    if (!searchActive) return; // only react when search is active
    setExpanded(containsSelected);
  }, [searchActive, containsSelected]);

  return (
    <div>
      <button
        onClick={() => setExpanded((e) => !e)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left py-1.5 hover:bg-accent/50 rounded-sm transition-colors group",
          isLinkedToHoveredPlan && "bg-primary/5 ring-1 ring-primary/30",
        )}
      >
        {expanded ? (
          <ChevronDown size={13} className="text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight size={13} className="text-muted-foreground shrink-0" />
        )}
        <span
          className={cn(
            "text-sm font-semibold leading-snug truncate flex-1",
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
              <StepButton
                key={step.turnId}
                step={step}
                isActive={isActive}
                isSelected={isSelected}
                searchActive={searchActive}
                onStepClick={onStepClick}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ActivityTimeline({
  jobId,
  jobState,
  onStepClick,
  selectedTurnId,
  searchActive,
}: {
  jobId: string;
  jobState?: string;
  onStepClick: (turnId: string) => void;
  selectedTurnId?: string | null;
  searchActive?: boolean;
}) {
  const timeline = useStore(selectActivityTimeline(jobId));
  const planSteps = useStore(selectJobPlan(jobId));
  const hoveredPlanItemId = useStore(selectHoveredPlanItemId);

  // When the job has reached a terminal state, force all activities to "done"
  // so the spinner stops.
  const jobFinished = !!jobState && TERMINAL_STATES.has(jobState);
  const activities = jobFinished
    ? timeline.activities.map((a) => a.status === "active" ? { ...a, status: "done" as const } : a)
    : timeline.activities;

  if (activities.length === 0 && planSteps.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 px-4 py-6">
        <ListTree size={20} className="text-muted-foreground" />
        <span className="text-xs text-muted-foreground text-center leading-relaxed">Activity will appear here as the agent works</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Plan panel — pinned at top of sidebar */}
      {planSteps.length > 0 && <PlanPanel jobId={jobId} />}
      {/* Activity log section header — only when plan is visible to separate them */}
      {planSteps.length > 0 && activities.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
          <ListTree size={12} className="text-muted-foreground shrink-0" />
          <span className="text-xs font-semibold text-muted-foreground">Activity Log</span>
          <span className="ml-auto text-[11px] text-muted-foreground/50 tabular-nums shrink-0">{activities.length}</span>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {activities.map((activity, i) => (
          <ActivitySection
            key={activity.activityId}
            activity={activity}
            isLast={i === activities.length - 1}
            selectedTurnId={selectedTurnId ?? null}
            onStepClick={onStepClick}
            searchActive={searchActive}
            highlightPlanItemId={hoveredPlanItemId}
          />
        ))}
      </div>
    </div>
  );
}
