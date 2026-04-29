/**
 * Timeline and plan step SSE event handlers.
 */

import type { PlanStep, ActivityTimelineStep } from "../types";
import type { SSEHandler, AppState } from "./types";

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export function handleProgressHeadline(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const headline = (payload.headline as string) || "";
  const headlinePast = (payload.headlinePast as string) || headline;
  const timestamp = (payload.timestamp as string) || new Date().toISOString();
  const summary = (payload.summary as string) || "";
  const existing = state.jobs[jobId];

  // Accumulate timeline entry
  const prevTimeline = state.timelines[jobId] ?? [];
  // Mark all remaining previous entries as inactive
  const deactivated = prevTimeline.map((e) =>
    e.active ? { ...e, active: false } : e,
  );
  const newTimeline = [
    ...deactivated,
    { headline, headlinePast, summary, timestamp, active: true },
  ];

  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          progressHeadline: headline,
          progressSummary: summary,
        },
      },
      timelines: { ...state.timelines, [jobId]: newTimeline },
    };
  }
  return {
    timelines: { ...state.timelines, [jobId]: newTimeline },
  };
}

export function handleAgentPlanUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const rawSteps = (payload.steps as Array<{ label: string; status: string; summary?: string; toolCount?: number; filesWritten?: string[]; durationMs?: number }>) || [];
  const typed: PlanStep[] = rawSteps.map((s) => ({
    label: s.label,
    status: (s.status as PlanStep["status"]) || "pending",
    summary: s.summary,
    toolCount: s.toolCount,
    filesWritten: s.filesWritten,
    durationMs: s.durationMs,
  }));
  return {
    plans: { ...state.plans, [jobId]: typed },
  };
}

export function handlePlanStepUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const planStepId = payload.planStepId as string;
  const label = payload.label as string;
  if (!jobId || !planStepId || !label) return null;
  const validStatuses = ["done", "active", "pending", "skipped"] as const;
  const rawStatus = payload.status as string;
  const status: PlanStep["status"] = (validStatuses as readonly string[]).includes(rawStatus)
    ? (rawStatus as PlanStep["status"])
    : "pending";
  const summary = payload.summary as string | undefined;
  const toolCount = payload.toolCount as number | undefined;
  const filesWritten = payload.filesWritten as string[] | undefined;
  const durationMs = payload.durationMs as number | undefined;
  const order = payload.order as number | undefined;

  const existing = state.plans[jobId] ?? [];
  const idx = existing.findIndex((s) => s.planStepId === planStepId);
  const updated: PlanStep = {
    planStepId,
    label,
    status,
    summary,
    toolCount,
    filesWritten,
    durationMs,
  };

  let newPlan: PlanStep[];
  if (idx >= 0) {
    // Update existing step in place
    newPlan = [...existing];
    newPlan[idx] = updated;
  } else if (order === 0 && existing.length > 0) {
    // New step with order=0 that doesn't exist in current plan →
    // start of a new plan generation.  Replace the old plan.
    newPlan = [updated];
  } else {
    newPlan = [...existing, updated];
  }
  return {
    plans: { ...state.plans, [jobId]: newPlan },
  };
}

export function handleTurnSummary(state: AppState, payload: Record<string, unknown>, getFresh: () => AppState): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const turnId = payload.turnId as string;
  const title = payload.title as string;
  const activityId = payload.activityId as string;
  const activityLabel = payload.activityLabel as string;
  const activityStatus = (payload.activityStatus as "active" | "done") || "active";
  const isNewActivity = payload.isNewActivity as boolean;
  const planItemId = (payload.planItemId as string | null) ?? null;

  // Read FRESH state (not the captured `state` from the top of dispatchSSEEvent)
  // because two SSE connections (global + job-scoped) may deliver the same event
  // in back-to-back macrotasks, and the captured `state` would be stale for the
  // second delivery.
  const freshTimeline = getFresh().activityTimelines[jobId] ?? { activities: [] };

  // Dedup: skip if this turnId was already recorded.
  // Exception: if the title changed, this is a merge update — patch in place.
  const alreadyExists = freshTimeline.activities.some((a) =>
    a.steps.some((s) => s.turnId === turnId),
  );
  if (alreadyExists) {
    // Check if the title differs (merge update from backend)
    const needsTitleUpdate = freshTimeline.activities.some((a) =>
      a.steps.some((s) => s.turnId === turnId && s.title !== title),
    );
    if (!needsTitleUpdate) return null;

    // Patch the existing step's title in place
    const activities = freshTimeline.activities.map((a) => ({
      ...a,
      steps: a.steps.map((s) =>
        s.turnId === turnId ? { ...s, title } : s,
      ),
    }));
    return {
      activityTimelines: {
        ...state.activityTimelines,
        [jobId]: { activities },
      },
    };
  }

  const activities = [...freshTimeline.activities];

  const step: ActivityTimelineStep = { turnId, title, activityId, planItemId };

  if (isNewActivity || activities.length === 0) {
    // Mark previous activity as done
    const prev = activities[activities.length - 1];
    if (prev) {
      activities[activities.length - 1] = { ...prev, status: "done" };
    }
    activities.push({
      activityId,
      label: activityLabel,
      status: activityStatus,
      steps: [step],
      planItemId,
    });
  } else {
    // Add step to the last activity and optionally update its label
    const last = activities[activities.length - 1];
    if (last) {
      activities[activities.length - 1] = {
        ...last,
        label: activityLabel,
        status: activityStatus,
        steps: [...last.steps, step],
      };
    }
  }

  return {
    activityTimelines: {
      ...state.activityTimelines,
      [jobId]: { activities },
    },
  };
}

export function handleStepEntriesReassigned(state: AppState, payload: Record<string, unknown>, getFresh: () => AppState): Partial<AppState> | null {
  // Classifier moved a turn to a different plan item — update planItemId
  const jobId = payload.jobId as string;
  const turnId = payload.turnId as string;
  const newStepId = payload.newStepId as string;

  const freshTimeline = getFresh().activityTimelines[jobId];
  if (!freshTimeline) return null;

  let changed = false;
  const activities = freshTimeline.activities.map((a) => ({
    ...a,
    steps: a.steps.map((s) => {
      if (s.turnId === turnId && s.planItemId !== newStepId) {
        changed = true;
        return { ...s, planItemId: newStepId };
      }
      return s;
    }),
  }));

  if (!changed) return null;
  return {
    activityTimelines: {
      ...state.activityTimelines,
      [jobId]: { activities },
    },
  };
}

export const timelineHandlers: Record<string, SSEHandler> = {
  progress_headline: handleProgressHeadline,
  agent_plan_updated: handleAgentPlanUpdated,
  plan_step_updated: handlePlanStepUpdated,
  turn_summary: handleTurnSummary,
  step_entries_reassigned: handleStepEntriesReassigned,
};
