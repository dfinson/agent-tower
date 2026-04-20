import { useState, useEffect, useRef, useCallback } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, Loader2, Circle, ListTree, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
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
  isVisible,
  searchActive,
  onStepClick,
}: {
  step: { turnId: string; title: string };
  isActive: boolean;
  isSelected: boolean;
  isVisible: boolean;
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
        !isSelected && isVisible && "bg-primary/5 border-l-2 border-primary/30",
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
  visibleStepTurnId,
  onStepClick,
  searchActive,
  highlightPlanItemId,
  expandSignal,
}: {
  activity: ActivityTimelineActivity;
  isLast: boolean;
  selectedTurnId: string | null;
  visibleStepTurnId?: string | null;
  onStepClick: (turnId: string) => void;
  searchActive?: boolean;
  highlightPlanItemId?: string | null;
  expandSignal: { gen: number; expand: boolean };
}) {
  const [expanded, setExpanded] = useState(activity.status === "active");

  // Respond to expand-all / collapse-all signal from parent
  const expandGen = useRef(expandSignal.gen);
  useEffect(() => {
    if (expandSignal.gen !== expandGen.current) {
      expandGen.current = expandSignal.gen;
      setExpanded(expandSignal.expand);
    }
  }, [expandSignal]);

  // Highlight when the hovered plan item matches this activity's plan link
  const isLinkedToHoveredPlan = !!highlightPlanItemId && activity.planItemId === highlightPlanItemId;

  // When search is driving the sidebar, auto-expand the activity containing
  // the matched step and collapse everything else.
  const containsSelected = !!selectedTurnId && activity.steps.some((s) => s.turnId === selectedTurnId);
  useEffect(() => {
    if (!searchActive) return; // only react when search is active
    setExpanded(containsSelected);
  }, [searchActive, containsSelected]);

  // Phase 4: Auto-expand when the user scrolls to content belonging to this activity
  const containsVisible = !!visibleStepTurnId && activity.steps.some((s) => s.turnId === visibleStepTurnId);
  useEffect(() => {
    if (containsVisible) setExpanded(true); // expand only — don't collapse others
  }, [containsVisible]);

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
            const isVisible = !!visibleStepTurnId && visibleStepTurnId === step.turnId;
            return (
              <StepButton
                key={step.turnId}
                step={step}
                isActive={isActive}
                isSelected={isSelected}
                isVisible={isVisible}
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
  visibleStepTurnId,
}: {
  jobId: string;
  jobState?: string;
  onStepClick: (turnId: string) => void;
  selectedTurnId?: string | null;
  searchActive?: boolean;
  visibleStepTurnId?: string | null;
}) {
  const timeline = useStore(selectActivityTimeline(jobId));
  const planSteps = useStore(selectJobPlan(jobId));
  const hoveredPlanItemId = useStore(selectHoveredPlanItemId);

  // Expand-all / collapse-all toggle
  const [allExpanded, setAllExpanded] = useState(false);
  const [expandSignal, setExpandSignal] = useState({ gen: 0, expand: false });
  const toggleAll = useCallback(() => {
    const next = !allExpanded;
    setAllExpanded(next);
    setExpandSignal((prev) => ({ gen: prev.gen + 1, expand: next }));
  }, [allExpanded]);

  // When the job has reached a terminal state, force all activities to "done"
  // so the spinner stops.
  const jobFinished = !!jobState && TERMINAL_STATES.has(jobState);
  const rawActivities = jobFinished
    ? timeline.activities.map((a) => a.status === "active" ? { ...a, status: "done" as const } : a)
    : timeline.activities;

  // Post-process: merge consecutive activities with the same label to
  // eliminate duplicate headings, then absorb single-step activities
  // into their neighbor so there are no naked orphan steps.
  const merged = rawActivities.reduce<typeof rawActivities>((acc, act) => {
    const prev = acc[acc.length - 1];
    if (prev && prev.label === act.label) {
      // Merge into previous: combine steps, keep latest status
      acc[acc.length - 1] = {
        ...prev,
        steps: [...prev.steps, ...act.steps],
        status: act.status,
        planItemId: act.planItemId ?? prev.planItemId,
      };
    } else {
      acc.push(act);
    }
    return acc;
  }, []);

  // Absorb single-step activities into the next (or previous) neighbor
  const activities: typeof merged = [];
  for (let i = 0; i < merged.length; i++) {
    const act = merged[i]!;
    if (act.steps.length === 1 && merged.length > 1) {
      // Try absorb into the next activity
      const next = merged[i + 1];
      if (next) {
        merged[i + 1] = {
          ...next,
          steps: [...act.steps, ...next.steps],
          planItemId: next.planItemId ?? act.planItemId,
        };
        continue;
      }
      // No next — absorb into previous
      const prev = activities[activities.length - 1];
      if (prev) {
        activities[activities.length - 1] = {
          ...prev,
          steps: [...prev.steps, ...act.steps],
          planItemId: prev.planItemId ?? act.planItemId,
        };
        continue;
      }
    }
    activities.push(act);
  }

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
          {activities.length > 1 && (
            <button
              onClick={toggleAll}
              className="ml-auto text-muted-foreground/60 hover:text-muted-foreground transition-colors"
              title={allExpanded ? "Collapse all" : "Expand all"}
            >
              {allExpanded ? <ChevronsDownUp size={13} /> : <ChevronsUpDown size={13} />}
            </button>
          )}
          <span className={cn("text-[11px] text-muted-foreground/50 tabular-nums shrink-0", activities.length <= 1 && "ml-auto")}>{activities.length}</span>
        </div>
      )}
      {/* Minimal toggle header when no plan panel but multiple activities */}
      {planSteps.length === 0 && activities.length > 1 && (
        <div className="flex items-center justify-end px-3 py-1.5">
          <button
            onClick={toggleAll}
            className="text-muted-foreground/60 hover:text-muted-foreground transition-colors"
            title={allExpanded ? "Collapse all" : "Expand all"}
          >
            {allExpanded ? <ChevronsDownUp size={13} /> : <ChevronsUpDown size={13} />}
          </button>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {activities.map((activity, i) => (
          <ActivitySection
            key={activity.activityId}
            activity={activity}
            isLast={i === activities.length - 1}
            selectedTurnId={selectedTurnId ?? null}
            visibleStepTurnId={visibleStepTurnId}
            onStepClick={onStepClick}
            searchActive={searchActive}
            highlightPlanItemId={hoveredPlanItemId}
            expandSignal={expandSignal}
          />
        ))}
      </div>
    </div>
  );
}
