/**
 * Zustand store — single source of truth for application state.
 *
 * SSE events are processed through a central event dispatcher that
 * updates the store. Components read from the store via selectors.
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types — re-exported from ./types for backward compatibility.
// ---------------------------------------------------------------------------

import { fetchSDKs, fetchModels, createTerminalSession as apiCreateTerminalSession, deleteTerminalSession as apiDeleteTerminalSession } from "../api/client";
import { sseHandlers, enrichJob } from "./sseHandlers";
export { enrichJob } from "./sseHandlers";

// Re-export all types so existing `import { ... } from "../store"` still works
export type {
  ConnectionStatus,
  JobSummary,
  ApprovalRequest,
  BatchApproval,
  LogLine,
  TranscriptEntry,
  PlanStep,
  TimelineEntry,
  ActivityTimelineStep,
  ActivityTimelineActivity,
  ActivityTimelineState,
  TerminalSession,
  AppState,
} from "./types";

// Re-export all selectors
export {
  selectJobs,
  selectConnectionStatus,
  selectReconnectAttempt,
  selectApprovals,
  selectBatchApprovals,
  selectJobLogs,
  selectJobTranscript,
  selectJobDiffs,
  selectJobStory,
  selectStreamingToolOutput,
  selectStreamingReasoning,
  selectActiveJobs,
  selectSignoffJobs,
  selectAttentionJobs,
  selectArchivedJobs,
  selectArchivedCount,
  selectJobTimeline,
  selectJobPlan,
  selectActivityTimeline,
  selectHoveredPlanItemId,
} from "./selectors";

import type {
  AppState,
  PlanStep,
  TimelineEntry,
  ActivityTimelineState,
  ActivityTimelineStep,
  ActivityTimelineActivity,
  TerminalSession,
} from "./types";

function pickDefaultModelId(models: Array<{ value: string; isDefault: boolean }>): string | null {
  const flagged = models.find((m) => m.isDefault);
  return flagged?.value ?? models[0]?.value ?? null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------



// ---------------------------------------------------------------------------
// LRU eviction for per-job data — prevents unbounded memory growth.
// ---------------------------------------------------------------------------

/** Max jobs whose logs/transcript/diffs we keep in memory. */
const MAX_CACHED_JOBS = 30;

/** Track access order: most-recent jobId at the end. */
const _jobAccessOrder: string[] = [];

/** Mark a jobId as recently accessed; returns jobIds to evict (if over limit). */
function touchJob(jobId: string): string[] {
  const idx = _jobAccessOrder.indexOf(jobId);
  if (idx >= 0) _jobAccessOrder.splice(idx, 1);
  _jobAccessOrder.push(jobId);
  const evict: string[] = [];
  while (_jobAccessOrder.length > MAX_CACHED_JOBS) {
    evict.push(_jobAccessOrder.shift()!);
  }
  return evict;
}

/** Evict per-job data for stale jobs from a state snapshot. */
function evictStaleJobs(
  state: Pick<AppState, "logs" | "transcript" | "diffs" | "stories" | "plans" | "timelines" | "activityTimelines" | "streamingMessages" | "streamingToolOutput">,
  evictIds: string[],
): Partial<AppState> | null {
  if (evictIds.length === 0) return null;
  const logs = { ...state.logs };
  const transcript = { ...state.transcript };
  const diffs = { ...state.diffs };
  const stories = { ...state.stories };
  const plans = { ...state.plans };
  const timelines = { ...state.timelines };
  const activityTimelines = { ...state.activityTimelines };
  let streamingMessages = state.streamingMessages;
  let streamingToolOutput = state.streamingToolOutput;
  let streamingChanged = false;
  let toolOutputChanged = false;
  for (const id of evictIds) {
    delete logs[id];
    delete transcript[id];
    delete diffs[id];
    delete stories[id];
    delete plans[id];
    delete timelines[id];
    delete activityTimelines[id];
    // Clean streaming messages for evicted jobs
    for (const key of Object.keys(streamingMessages)) {
      if (key.startsWith(`${id}:`)) {
        if (!streamingChanged) { streamingMessages = { ...streamingMessages }; streamingChanged = true; }
        delete streamingMessages[key];
      }
    }
    for (const key of Object.keys(streamingToolOutput)) {
      if (key.startsWith(`${id}:`)) {
        if (!toolOutputChanged) { streamingToolOutput = { ...streamingToolOutput }; toolOutputChanged = true; }
        delete streamingToolOutput[key];
      }
    }
  }
  return { logs, transcript, diffs, stories, plans, timelines, activityTimelines, streamingMessages, streamingToolOutput };
}

/** Rebuild activity timeline state from a flat list of turn summary payloads (hydration). */
function _rebuildActivityTimeline(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  summaries: Array<Record<string, any>>,
): ActivityTimelineState {
  const activities: ActivityTimelineActivity[] = [];
  const seenTurnIds = new Set<string>();
  for (const s of summaries) {
    const turnId = s.turnId ?? "";
    if (seenTurnIds.has(turnId)) continue;
    seenTurnIds.add(turnId);
    const planItemId = (s.planItemId as string | null) ?? null;
    const step: ActivityTimelineStep = {
      turnId,
      title: s.title ?? "",
      activityId: s.activityId ?? "",
      planItemId,
    };
    const isNew = s.isNewActivity as boolean;
    // When a turn references an activityId we already built, append to that
    // activity rather than creating a duplicate (handles resumed plan steps).
    const existingById = activities.find((a) => a.activityId === (s.activityId ?? ""));
    if (existingById && !isNew) {
      existingById.steps.push(step);
      existingById.label = s.activityLabel ?? existingById.label;
      existingById.status = (s.activityStatus as "active" | "done") ?? existingById.status;
    } else if (existingById && isNew) {
      // isNewActivity was set but this activityId already exists — resume it
      existingById.steps.push(step);
      existingById.status = (s.activityStatus as "active" | "done") ?? existingById.status;
    } else if (isNew || activities.length === 0) {
      const prev = activities[activities.length - 1];
      if (prev) prev.status = "done";
      activities.push({
        activityId: s.activityId ?? "",
        label: s.activityLabel ?? "",
        status: (s.activityStatus as "active" | "done") ?? "active",
        steps: [step],
        planItemId,
      });
    } else {
      const last = activities[activities.length - 1];
      if (last) {
        last.steps.push(step);
        last.label = s.activityLabel ?? last.label;
        last.status = (s.activityStatus as "active" | "done") ?? last.status;
      }
    }
  }
  return { activities };
}

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

// Module-level singleton guard: ensures initSdksAndModels is only ever
// in-flight once, even if called concurrently from multiple components.
let _sdkInitPromise: Promise<void> | null = null;

/** Reset the SDK init guard — for use in tests only. */
export function _resetSdkInitForTesting() {
  _sdkInitPromise = null;
}

export const useStore = create<AppState>((set, get) => ({
  jobs: {},
  approvals: {},
  batchApprovals: {},
  logs: {},
  transcript: {},
  diffs: {},
  stories: {},
  plans: {},
  timelines: {},
  activityTimelines: {},
  streamingMessages: {},
  streamingToolOutput: {},
  streamingReasoning: {},
  telemetryVersions: {},
  connectionStatus: "reconnecting",
  reconnectAttempt: 0,
  hoveredPlanItemId: null,
  policySettingsVersion: 0,

  // SDK + model catalogue
  sdks: [],
  defaultSdk: null,
  sdksLoading: true,
  modelsBySdk: {},
  defaultModelBySdk: {},
  modelsLoadingBySdk: {},

  // Terminal state
  terminalDrawerOpen: false,
  terminalDrawerHeight: 300,
  terminalSessions: {},
  activeTerminalTab: null,

  setConnectionStatus: (status) =>
    get().connectionStatus !== status && set({ connectionStatus: status }),

  setReconnectAttempt: (attempt) => set({ reconnectAttempt: attempt }),

  initSdksAndModels: async () => {
    // No-op if already done (success or failure)
    if (!get().sdksLoading) return;
    // Coalesce concurrent callers onto the same in-flight promise
    if (_sdkInitPromise) return _sdkInitPromise;
    _sdkInitPromise = (async () => {
      try {
        const r = await fetchSDKs();
        set({ sdks: r.sdks, defaultSdk: r.default, sdksLoading: false });
        // Pre-load models for the default SDK
        await get().loadModelsForSdk(r.default);
      } catch (err) {
        console.error("Failed to fetch SDKs", err);
        set({ sdksLoading: false });
      }
    })();
    return _sdkInitPromise;
  },

  loadModelsForSdk: async (sdkId: string) => {
    // Skip if already loaded or currently loading
    const state = get();
    if (state.modelsBySdk[sdkId] !== undefined || state.modelsLoadingBySdk[sdkId]) return;
    set((s) => ({ modelsLoadingBySdk: { ...s.modelsLoadingBySdk, [sdkId]: true } }));
    try {
      const models = await fetchModels(sdkId);
      const mapped = models
        .map((x) => ({
          value: String(x.id ?? x.name ?? ""),
          label: String(x.name ?? x.id ?? "unknown"),
          isDefault: Boolean(
            (typeof x.default === "boolean" && x.default) ||
            (typeof x.isDefault === "boolean" && x.isDefault) ||
            (typeof x.is_default === "boolean" && x.is_default),
          ),
        }))
        .filter((x) => x.value);
      set((s) => ({
        modelsBySdk: { ...s.modelsBySdk, [sdkId]: mapped.map(({ value, label }) => ({ value, label })) },
        defaultModelBySdk: { ...s.defaultModelBySdk, [sdkId]: pickDefaultModelId(mapped) },
        modelsLoadingBySdk: { ...s.modelsLoadingBySdk, [sdkId]: false },
      }));
    } catch (err) {
      console.error(`Failed to fetch models for SDK "${sdkId}"`, err);
      set((s) => ({
        modelsBySdk: { ...s.modelsBySdk, [sdkId]: [] },
        defaultModelBySdk: { ...s.defaultModelBySdk, [sdkId]: null },
        modelsLoadingBySdk: { ...s.modelsLoadingBySdk, [sdkId]: false },
      }));
    }
  },

  applySnapshot: (jobs, approvals) => {
    const jobMap = Object.fromEntries(jobs.map((j) => [j.id, enrichJob(j)]));
    const validApprovals = approvals.filter(
      (a) => jobMap[a.jobId]?.state === "waiting_for_approval",
    );
    set({
      jobs: jobMap,
      approvals: Object.fromEntries(validApprovals.map((a) => [a.id, a])),
    });
  },

  hydrateJob: (snapshot) => {
    const jobId = snapshot.job.id;
    const evictIds = touchJob(jobId);
    set((s) => {
      // Remove stale approvals for this job before merging fresh ones
      const keptApprovals = Object.fromEntries(
        Object.entries(s.approvals).filter(([, a]) => a.jobId !== jobId),
      );
      // Drop any in-flight streaming state for this job
      const streamingMessages = Object.fromEntries(
        Object.entries(s.streamingMessages).filter(([k]) => !k.startsWith(`${jobId}:`)),
      );
      const streamingToolOutput = Object.fromEntries(
        Object.entries(s.streamingToolOutput).filter(([k]) => !k.startsWith(`${jobId}:`)),
      );
      // Deduplicate transcript: remove tool_running entries whose tool has a
      // completed tool_call — both are persisted but only one should render.
      // Use turnId-scoped keys when available to avoid false-positive removal
      // of in-flight tool_running entries for the same tool name.
      const completedCallKeys = new Set<string>();
      for (const e of snapshot.transcript) {
        if (e.role === "tool_call" && e.toolName) {
          completedCallKeys.add(e.turnId ? `${e.toolName}::${e.turnId}` : e.toolName);
        }
      }
      const deduped = snapshot.transcript.filter((e) => {
        if (e.role !== "tool_running" || !e.toolName) return true;
        const key = e.turnId ? `${e.toolName}::${e.turnId}` : e.toolName;
        return !completedCallKeys.has(key);
      });
      return {
        ...evictStaleJobs(s, evictIds),
        jobs: { ...s.jobs, [jobId]: enrichJob(snapshot.job) },
        logs: { ...s.logs, [jobId]: snapshot.logs },
        transcript: { ...s.transcript, [jobId]: deduped },
        diffs: { ...s.diffs, [jobId]: snapshot.diff },
        approvals: {
          ...keptApprovals,
          ...Object.fromEntries(snapshot.approvals.map((a) => [a.id, a])),
        },
        streamingMessages,
        streamingToolOutput,
        timelines: {
          ...s.timelines,
          [jobId]: (snapshot.timeline ?? []).map((t: TimelineEntry) => ({ ...t, active: false })),
        },
        activityTimelines: {
          ...s.activityTimelines,
          [jobId]: _rebuildActivityTimeline(snapshot.turnSummaries ?? []),
        },
        // Hydrate plan steps from snapshot so plan survives page refresh
        plans: {
          ...s.plans,
          [jobId]: (snapshot.steps ?? [])
            .filter((p) => p.planStepId && p.label)
            .map((p) => ({
              planStepId: p.planStepId,
              label: p.label,
              status: (["done", "active", "pending", "skipped"].includes(p.status) ? p.status as PlanStep["status"] : "pending"),
              summary: p.summary,
              toolCount: p.toolCount,
              filesWritten: p.filesWritten,
              durationMs: p.durationMs,
            })),
        },
      };
    });
  },

  dispatchSSEEvent: (eventType, data) => {
    const handler = sseHandlers[eventType];
    if (!handler) return;
    const state = get();
    const payload = data as Record<string, unknown>;
    const update = handler(state, payload, get);
    if (update !== null) {
      set(update);
    }
  },
  // ------------------------------------------------------------------
  // Terminal actions
  // ------------------------------------------------------------------

  toggleTerminalDrawer: () =>
    set((s) => ({ terminalDrawerOpen: !s.terminalDrawerOpen })),

  setTerminalDrawerHeight: (height) => set({ terminalDrawerHeight: height }),

  setActiveTerminalTab: (id) => set({ activeTerminalTab: id }),

  addTerminalSession: (session) =>
    set((s) => ({
      terminalSessions: { ...s.terminalSessions, [session.id]: session },
      activeTerminalTab: session.id,
      terminalDrawerOpen: true,
    })),

  removeTerminalSession: (id) =>
    set((s) => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { [id]: _removed, ...rest } = s.terminalSessions;
      // Delete the session on the backend (fire-and-forget)
      apiDeleteTerminalSession(id).catch((err) => console.error("Failed to delete terminal session", err));
      const remaining = Object.keys(rest);
      return {
        terminalSessions: rest,
        activeTerminalTab:
          s.activeTerminalTab === id
            ? remaining.length > 0
              ? remaining[remaining.length - 1]
              : null
            : s.activeTerminalTab,
        // Auto-close the drawer when no sessions remain
        terminalDrawerOpen: remaining.length > 0 ? s.terminalDrawerOpen : false,
      };
    }),

  createTerminalSession: async (opts) => {
    try {
      const data = await apiCreateTerminalSession({
        cwd: opts?.cwd ?? null,
        jobId: opts?.jobId ?? null,
        promptLabel: opts?.label ?? null,
      });

      const baseLabel = opts?.label || data.cwd?.split("/").pop() || "Terminal";

      // Auto-number duplicate labels so tabs are distinguishable (e.g. "main ×2")
      const existingLabels = Object.values(get().terminalSessions).map((s) => s.label);
      const collision = existingLabels.filter(
        (l) => l === baseLabel || l?.startsWith(baseLabel + " ×"),
      ).length;
      const label = collision > 0 ? `${baseLabel} ×${collision + 1}` : baseLabel;

      const session: TerminalSession = {
        id: data.id,
        label,
        cwd: data.cwd,
        jobId: data.jobId ?? opts?.jobId,
      };

      // On mobile, auto-maximise the drawer when opening a job terminal.
      // Cap at 50% of viewport height to match the drag-resize max for small screens.
      const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
      const drawerHeight = isMobile
        ? Math.floor(window.innerHeight * 0.5)
        : get().terminalDrawerHeight;

      set((s) => ({
        terminalSessions: { ...s.terminalSessions, [session.id]: session },
        activeTerminalTab: session.id,
        terminalDrawerOpen: true,
        terminalDrawerHeight: drawerHeight,
      }));
    } catch (e) {
      console.error("[terminal] Error creating session:", e);
    }
  },

  setHoveredPlanItemId: (id) => set({ hoveredPlanItemId: id }),

  setStory: (jobId, story) => set((state) => ({
    stories: { ...state.stories, [jobId]: story },
  })),
}));

// Expose the store on window so Playwright capture scripts can inject
// test data (e.g. approval events) deterministically without relying on SSE timing.
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>)["__codeplane_store"] = useStore;
}

