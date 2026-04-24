/**
 * Individual SSE event handlers extracted from the Zustand store.
 *
 * Each handler takes (state, payload, getFresh) and returns a partial
 * state update or null if no change is needed.
 */

import type {
  AppState,
  JobSummary,
  ApprovalRequest,
  LogLine,
  TranscriptEntry,
  PlanStep,
  ActivityTimelineStep,
  ConnectionStatus,
} from "./index";
import type { DiffFileModel } from "../api/types";

export type SSEHandler = (
  state: AppState,
  payload: Record<string, unknown>,
  getFresh: () => AppState,
) => Partial<AppState> | null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MODEL_DOWNGRADE_RE = /^Model downgraded: requested (.+?) but received (.+)$/;

/** Finalize all active/pending plan steps to a terminal status. */
function finalizePlanSteps(plan: PlanStep[] | undefined, finalStatus: "done" | "skipped"): PlanStep[] | undefined {
  return plan?.map((s) => (s.status === "active" || s.status === "pending" ? { ...s, status: finalStatus } : s));
}

/** Enrich a job loaded from the REST API with parsed model downgrade info. */
export function enrichJob(job: JobSummary): JobSummary {
  if (job.modelDowngraded) return job; // already enriched (e.g. from SSE)
  if (!job.failureReason) return job;
  const m = MODEL_DOWNGRADE_RE.exec(job.failureReason);
  if (!m) return job;
  return { ...job, modelDowngraded: true, requestedModel: m[1], actualModel: m[2] };
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

function handleJobStateChanged(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const newState = payload.newState as string;
  const existing = state.jobs[jobId];
  if (existing) {
    // If the job is leaving waiting_for_approval without an
    // approval_resolved event (e.g. server-restart recovery), evict any
    // stale unresolved approvals for this job so the mobile badge stays
    // in sync with the column content.
    let approvals = state.approvals;
    if (newState !== "waiting_for_approval") {
      const staleIds = Object.keys(state.approvals).filter(
        (id) => state.approvals[id]?.jobId === jobId && !state.approvals[id]?.resolvedAt,
      );
      if (staleIds.length > 0) {
        approvals = { ...state.approvals };
        for (const id of staleIds) delete approvals[id];
      }
    }

    // Finalize plan steps on cancel
    const isCanceled = newState === "canceled";
    const existingPlan = isCanceled ? state.plans[jobId] : undefined;
    const finalPlan = finalizePlanSteps(existingPlan, "skipped");

    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          state: newState,
          updatedAt: (payload.timestamp as string) ?? existing.updatedAt,
        },
      },
      ...(finalPlan && { plans: { ...state.plans, [jobId]: finalPlan } }),
      ...(approvals !== state.approvals && { approvals }),
    };
  }
  return null;
}

function handleJobSetupProgress(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const step = payload.step as string;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: { ...existing, setupStep: step },
      },
    };
  }
  return null;
}

function handleLogLine(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const entry: LogLine = {
    jobId,
    seq: payload.seq as number,
    timestamp: payload.timestamp as string,
    level: payload.level as string,
    message: payload.message as string,
    context: (payload.context as Record<string, unknown> | null) ?? null,
  };
  const existing = state.logs[jobId] ?? [];
  const updated = [...existing, entry];
  return {
    logs: { ...state.logs, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
  };
}

function handleTranscriptUpdate(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const role = payload.role as string;

  // agent_delta: accumulate streaming text per turn, don't add to transcript
  if (role === "agent_delta") {
    const turnId = (payload.turnId as string | undefined) ?? "__default__";
    const key = `${jobId}:${turnId}`;
    const delta = (payload.content as string) ?? "";
    return {
      streamingMessages: {
        ...state.streamingMessages,
        [key]: (state.streamingMessages[key] ?? "") + delta,
      },
    };
  }

  // tool_output_delta: accumulate streaming tool output, don't add to transcript
  if (role === "tool_output_delta") {
    const toolCallId = (payload.toolCallId as string | undefined) ?? (payload.toolName as string | undefined) ?? "__tool__";
    const key = `${jobId}:${toolCallId}`;
    const chunk = (payload.content as string) ?? "";
    return {
      streamingToolOutput: {
        ...state.streamingToolOutput,
        [key]: (state.streamingToolOutput[key] ?? "") + chunk,
      },
    };
  }

  // reasoning_delta: accumulate streaming reasoning per turn, don't add to transcript
  if (role === "reasoning_delta") {
    const turnId = (payload.turnId as string | undefined) ?? "__default__";
    const key = `${jobId}:${turnId}`;
    const delta = (payload.content as string) ?? "";
    return {
      streamingReasoning: {
        ...state.streamingReasoning,
        [key]: (state.streamingReasoning[key] ?? "") + delta,
      },
    };
  }

  const entry: TranscriptEntry = {
    jobId,
    seq: payload.seq as number,
    timestamp: payload.timestamp as string,
    role,
    content: payload.content as string,
    title: payload.title as string | undefined,
    turnId: payload.turnId as string | undefined,
    toolName: payload.toolName as string | undefined,
    toolArgs: payload.toolArgs as string | undefined,
    toolResult: payload.toolResult as string | undefined,
    toolSuccess: payload.toolSuccess as boolean | undefined,
    toolIssue: payload.toolIssue as string | undefined,
    toolIntent: payload.toolIntent as string | undefined,
    toolTitle: payload.toolTitle as string | undefined,
    toolDisplay: payload.toolDisplay as string | undefined,
    toolDisplayFull: payload.toolDisplayFull as string | undefined,
    toolDurationMs: payload.toolDurationMs as number | undefined,
    toolVisibility: payload.toolVisibility as string | undefined,
  };
  const existing = state.transcript[jobId] ?? [];

  // When a tool_call arrives, replace any matching tool_running entry
  // (same toolName, and same turnId when both are present) so the
  // in-progress placeholder is superseded.
  let base = existing;
  if (entry.role === "tool_call") {
    const before = base.length;
    base = base.filter((e) => {
      if (e.role !== "tool_running" || e.toolName !== entry.toolName) return true;
      // If both entries have a turnId, they must match to be considered the same call.
      if (entry.turnId && e.turnId && entry.turnId !== e.turnId) return true;
      return false;
    });
    // If we replaced something, update both transcript and step index.
    if (base.length < before) {
      const updated = [...base, entry];

      return {
        transcript: { ...state.transcript, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
      };
    }
  }

  // Deduplicate: two SSE connections (global + job-scoped) may deliver
  // the same event; skip if identical role+content+timestamp already present.
  if (existing.some((e) => e.timestamp === entry.timestamp && e.role === entry.role && e.content === entry.content)) {
    return null;
  }
  const updated = [...existing, entry];

  // When a complete agent message arrives, clear streaming state for that turn.
  let streamingMessages = state.streamingMessages;
  if (entry.role === "agent") {
    const key = entry.turnId ? `${jobId}:${entry.turnId}` : `${jobId}:__default__`;
    if (key in streamingMessages) {
      streamingMessages = { ...streamingMessages };
      delete streamingMessages[key];
    }
  }

  // When a tool_call (completion) arrives, clear streaming tool output.
  let streamingToolOutput = state.streamingToolOutput;
  if (entry.role === "tool_call") {
    // Clear all streaming entries for this job (tool call IDs vary)
    const prefix = `${jobId}:`;
    const keys = Object.keys(streamingToolOutput).filter((k) => k.startsWith(prefix));
    if (keys.length > 0) {
      streamingToolOutput = { ...streamingToolOutput };
      for (const k of keys) delete streamingToolOutput[k];
    }
  }

  // When a complete reasoning message arrives, clear streaming reasoning for that turn.
  let streamingReasoning = state.streamingReasoning;
  if (entry.role === "reasoning") {
    const key = entry.turnId ? `${jobId}:${entry.turnId}` : `${jobId}:__default__`;
    if (key in streamingReasoning) {
      streamingReasoning = { ...streamingReasoning };
      delete streamingReasoning[key];
    }
  }

  return {
    transcript: { ...state.transcript, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
    streamingMessages,
    streamingToolOutput,
    streamingReasoning,
  };
}

function handleAgentPlanUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
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

function handleProgressHeadline(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
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

function handleApprovalRequested(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const approval: ApprovalRequest = {
    id: payload.approvalId as string,
    jobId: payload.jobId as string,
    description: payload.description as string,
    proposedAction: (payload.proposedAction as string | null) ?? null,
    requestedAt: (payload.timestamp as string) ?? new Date().toISOString(),
    resolvedAt: null,
    resolution: null,
    requiresExplicitApproval: (payload.requiresExplicitApproval as boolean) ?? false,
  };
  return {
    approvals: { ...state.approvals, [approval.id]: approval },
  };
}

function handleApprovalResolved(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const approvalId = payload.approvalId as string;
  const existing = state.approvals[approvalId];
  if (existing) {
    return {
      approvals: {
        ...state.approvals,
        [approvalId]: {
          ...existing,
          resolution: payload.resolution as string,
          resolvedAt: payload.timestamp as string,
        },
      },
    };
  }
  return null;
}

function handleSnapshot(_state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobs = (payload.jobs as JobSummary[]) ?? [];
  const rawApprovals =
    (payload.pendingApprovals as ApprovalRequest[]) ?? [];
  const jobMap = Object.fromEntries(jobs.map((j) => [j.id, enrichJob(j)]));
  // Drop approvals whose job is no longer in waiting_for_approval.
  // This covers the server-restart recovery path where the backend resets
  // the job to running without resolving its pending approval in the DB,
  // and the SSE gap is large enough that only a snapshot is sent (no
  // job_state_changed replay event to trigger the in-flight eviction).
  const approvals = rawApprovals.filter(
    (a) => jobMap[a.jobId]?.state === "waiting_for_approval",
  );
  return {
    jobs: jobMap,
    approvals: Object.fromEntries(approvals.map((a) => [a.id, a])),
  };
}

function handleSessionHeartbeat(state: AppState): Partial<AppState> | null {
  if (state.connectionStatus !== "connected") {
    return { connectionStatus: "connected" as ConnectionStatus };
  }
  return null;
}

function handleJobReview(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const prUrl = (payload.prUrl as string | null) ?? null;
  const resolution = (payload.resolution as string | null) ?? null;
  const mergeStatus = (payload.mergeStatus as string | null) ?? null;
  const modelDowngraded = (payload.modelDowngraded as boolean) ?? false;
  const requestedModel = (payload.requestedModel as string | null) ?? null;
  const actualModel = (payload.actualModel as string | null) ?? null;
  const existing = state.jobs[jobId];
  if (existing) {
    const finalPlan = finalizePlanSteps(state.plans[jobId], "done");
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          state: "review",
          ...(prUrl && { prUrl }),
          ...(resolution && { resolution }),
          ...(mergeStatus && { mergeStatus }),
          failureReason: null,
          ...(modelDowngraded && { modelDowngraded, requestedModel, actualModel }),
        },
      },
      ...(finalPlan && { plans: { ...state.plans, [jobId]: finalPlan } }),
    };
  }
  return null;
}

function handleJobCompleted(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const resolution = (payload.resolution as string | null) ?? null;
  const prUrl = (payload.prUrl as string | null) ?? null;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          state: "completed",
          ...(resolution && { resolution }),
          ...(prUrl && { prUrl }),
        },
      },
    };
  }
  return null;
}

function handleJobFailed(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const reason = (payload.reason as string | null) ?? "Unknown error";
  const existing = state.jobs[jobId];
  if (existing) {
    const finalPlan = finalizePlanSteps(state.plans[jobId], "skipped");
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          state: "failed",
          failureReason: reason,
        },
      },
      ...(finalPlan && { plans: { ...state.plans, [jobId]: finalPlan } }),
    };
  }
  return null;
}

function handleJobResolved(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const resolution = payload.resolution as string;
  const prUrl = (payload.prUrl as string | null) ?? null;
  const conflictFiles = (payload.conflictFiles as string[] | null) ?? null;
  const resolutionError = (payload.error as string | null) ?? null;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          resolution,
          prUrl: prUrl ?? existing.prUrl,
          conflictFiles,
          resolutionError,
          updatedAt: (payload.timestamp as string) ?? existing.updatedAt,
        },
      },
    };
  }
  return null;
}

function handleMergeCompleted(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          mergeStatus: "merged",
          updatedAt: (payload.timestamp as string) ?? existing.updatedAt,
        },
      },
    };
  }
  return null;
}

function handleMergeConflict(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const conflictFiles = (payload.conflictFiles as string[] | null) ?? null;
  const prUrl = (payload.prUrl as string | null) ?? null;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          mergeStatus: "conflict",
          conflictFiles,
          prUrl: prUrl ?? existing.prUrl,
          updatedAt: (payload.timestamp as string) ?? existing.updatedAt,
        },
      },
    };
  }
  return null;
}

function handleJobArchived(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          archivedAt: new Date().toISOString(),
        },
      },
    };
  }
  return null;
}

function handleDiffUpdate(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const changedFiles = (payload.changedFiles as DiffFileModel[]) ?? [];
  return {
    diffs: { ...state.diffs, [jobId]: changedFiles },
  };
}

function handleSessionResumed(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const timestamp = payload.timestamp as string;
  const divider: TranscriptEntry = {
    jobId,
    seq: -99,
    timestamp,
    role: "divider",
    content: "Session",
  };
  const existing = state.transcript[jobId] ?? [];
  // Deduplicate: two SSE connections may deliver the same event
  const resetFields = {
    state: "running",
    resolution: null,
    conflictFiles: null,
    failureReason: null,
    progressHeadline: null,
    progressSummary: null,
    archivedAt: null,
    modelDowngraded: false,
    requestedModel: null,
    actualModel: null,
    prUrl: null,
    mergeStatus: null,
    completedAt: null,
  };
  if (existing.some((e) => e.role === "divider" && e.timestamp === divider.timestamp)) {
    return { jobs: state.jobs[jobId] ? { ...state.jobs, [jobId]: { ...state.jobs[jobId], ...resetFields } } : state.jobs };
  }
  return {
    transcript: { ...state.transcript, [jobId]: [...existing, divider] },
    jobs: state.jobs[jobId]
      ? { ...state.jobs, [jobId]: { ...state.jobs[jobId], ...resetFields } }
      : state.jobs,
  };
}

function handleJobTitleUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const title = (payload.title as string | null) ?? null;
  const branch = (payload.branch as string | null) ?? null;
  const description = (payload.description as string | null) ?? null;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          ...(title && { title }),
          ...(branch && { branch }),
          ...(description && { description }),
        },
      },
    };
  }
  return null;
}

function handleToolGroupSummary(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const turnId = payload.turnId as string;
  const summary = payload.summary as string;
  const entries = state.transcript[jobId];
  if (!entries) return null;
  let changed = false;
  const patched = entries.map((e) => {
    if (e.role === "tool_call" && e.turnId === turnId && e.toolGroupSummary !== summary) {
      changed = true;
      return { ...e, toolGroupSummary: summary };
    }
    return e;
  });
  if (!changed) return null;
  return { transcript: { ...state.transcript, [jobId]: patched } };
}

function handleModelDowngraded(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const requestedModel = payload.requestedModel as string;
  const actualModel = payload.actualModel as string;
  const existing = state.jobs[jobId];
  if (existing) {
    return {
      jobs: {
        ...state.jobs,
        [jobId]: {
          ...existing,
          modelDowngraded: true,
          requestedModel,
          actualModel,
        },
      },
    };
  }
  return null;
}

function handleTelemetryUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  // Increment the per-job version counter so MetricsPanel re-fetches.
  const jobId = payload.jobId as string;
  const prev = state.telemetryVersions[jobId] ?? 0;
  return {
    telemetryVersions: { ...state.telemetryVersions, [jobId]: prev + 1 },
  };
}

function handlePlanStepUpdated(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
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

function handleTurnSummary(state: AppState, payload: Record<string, unknown>, getFresh: () => AppState): Partial<AppState> | null {
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

function handleStepEntriesReassigned(state: AppState, payload: Record<string, unknown>, getFresh: () => AppState): Partial<AppState> | null {
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

// ---------------------------------------------------------------------------
// Lookup table
// ---------------------------------------------------------------------------

export const sseHandlers: Record<string, SSEHandler> = {
  job_state_changed: handleJobStateChanged,
  job_setup_progress: handleJobSetupProgress,
  log_line: handleLogLine,
  transcript_update: handleTranscriptUpdate,
  agent_plan_updated: handleAgentPlanUpdated,
  progress_headline: handleProgressHeadline,
  approval_requested: handleApprovalRequested,
  approval_resolved: handleApprovalResolved,
  snapshot: handleSnapshot,
  session_heartbeat: handleSessionHeartbeat,
  job_review: handleJobReview,
  job_completed: handleJobCompleted,
  job_failed: handleJobFailed,
  job_resolved: handleJobResolved,
  merge_completed: handleMergeCompleted,
  merge_conflict: handleMergeConflict,
  job_archived: handleJobArchived,
  diff_update: handleDiffUpdate,
  session_resumed: handleSessionResumed,
  job_title_updated: handleJobTitleUpdated,
  tool_group_summary: handleToolGroupSummary,
  model_downgraded: handleModelDowngraded,
  telemetry_updated: handleTelemetryUpdated,
  plan_step_updated: handlePlanStepUpdated,
  turn_summary: handleTurnSummary,
  step_entries_reassigned: handleStepEntriesReassigned,
};
