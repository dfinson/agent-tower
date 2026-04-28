/**
 * Zustand store — single source of truth for application state.
 *
 * SSE events are processed through a central event dispatcher that
 * updates the store. Components read from the store via selectors.
 */

import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types — inline until schema generation (npm run generate:api) is wired up.
// These mirror the CamelModel shapes from the backend and MUST be replaced
// by imports from ../api/types once that module is populated.
// See: frontend/src/api/types.ts for the planned generated aliases.
// ---------------------------------------------------------------------------

import type { DiffFileModel, SDKInfo, StoryResponse } from "../api/types";
import { fetchSDKs, fetchModels, createTerminalSession as apiCreateTerminalSession, deleteTerminalSession as apiDeleteTerminalSession } from "../api/client";
import { sseHandlers, enrichJob } from "./sseHandlers";
export { enrichJob } from "./sseHandlers";

function pickDefaultModelId(models: Array<{ value: string; isDefault: boolean }>): string | null {
  const flagged = models.find((m) => m.isDefault);
  return flagged?.value ?? models[0]?.value ?? null;
}

/** Connection status exposed to UI components. */
export type ConnectionStatus = "connected" | "connecting" | "reconnecting" | "disconnected";

/** Minimal job shape matching JobResponse from the backend. */
export interface JobSummary {
  id: string;
  repo: string;
  prompt: string;
  title?: string | null;
  description?: string | null;
  state: string;
  baseRef: string;
  worktreePath: string | null;
  branch: string | null;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
  prUrl?: string | null;
  resolution?: string | null;
  archivedAt?: string | null;
  mergeStatus?: string | null;
  worktreeName?: string | null;
  conflictFiles?: string[] | null;
  resolutionError?: string | null;
  failureReason?: string | null;
  progressHeadline?: string | null;
  progressSummary?: string | null;
  model?: string | null;
  modelDowngraded?: boolean;
  requestedModel?: string | null;
  actualModel?: string | null;
  sdk?: string;
  /** Current setup step for jobs in 'preparing' state (e.g. "creating_workspace"). */
  setupStep?: string | null;
}

export interface ApprovalRequest {
  id: string;
  jobId: string;
  description: string;
  proposedAction: string | null;
  requestedAt: string;
  resolvedAt: string | null;
  resolution: string | null;
  requiresExplicitApproval: boolean;
}

export interface LogLine {
  jobId: string;
  seq: number;
  timestamp: string;
  level: string;
  message: string;
  context: Record<string, unknown> | null;
}

export interface TranscriptEntry {
  jobId: string;
  seq: number;
  timestamp: string;
  role: string;
  content: string;
  // Rich fields — only present for specific roles
  title?: string;        // agent messages: optional annotation title
  turnId?: string;       // groups reasoning + tool_calls + message into one turn
  toolName?: string;     // tool_call: identifier
  toolArgs?: string;     // tool_call: JSON-serialised arguments
  toolResult?: string;   // tool_call: text output
  toolSuccess?: boolean; // tool_call: success flag
  toolIssue?: string;    // tool_call: short issue summary when attention is needed
  toolIntent?: string;   // tool_call: SDK-provided intent string (deterministic label)
  toolTitle?: string;    // tool_call: SDK-provided display title
  toolDisplay?: string;  // tool_call: deterministic per-tool label (e.g. "$ ls -la", "Read src/main.py")
  toolDisplayFull?: string;  // tool_call: same label without char truncation (for CSS-based responsive truncation)
  toolDurationMs?: number;  // tool_call: execution time in milliseconds
  toolVisibility?: string;  // tool_call: "hidden" | "collapsed" | "visible"
  // AI-generated group summary — patched in asynchronously via tool_group_summary SSE
  toolGroupSummary?: string;
}

export interface PlanStep {
  planStepId?: string;
  label: string;
  status: "done" | "active" | "pending" | "skipped";
  summary?: string;
  toolCount?: number;
  filesWritten?: string[];
  durationMs?: number;
}

export interface TimelineEntry {
  headline: string;
  headlinePast: string;
  summary: string;
  timestamp: string;
  active: boolean;
}

/** A single step in the activity timeline — one visible agent turn. */
export interface ActivityTimelineStep {
  turnId: string;
  title: string;
  activityId: string;
  planItemId?: string | null;
}

/** A retrospective grouping of steps in the activity timeline. */
export interface ActivityTimelineActivity {
  activityId: string;
  label: string;
  status: "active" | "done";
  steps: ActivityTimelineStep[];
  planItemId?: string | null;
}

/** Per-job activity timeline state. */
export interface ActivityTimelineState {
  activities: ActivityTimelineActivity[];
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
    if (isNew || activities.length === 0) {
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
// Store shape
// ---------------------------------------------------------------------------

/** Terminal session metadata tracked in the store. */
export interface TerminalSession {
  id: string;
  label: string;
  cwd?: string;
  jobId?: string | null;
}

export interface AppState {
  // Data slices
  jobs: Record<string, JobSummary>;
  approvals: Record<string, ApprovalRequest>;
  logs: Record<string, LogLine[]>; // keyed by jobId
  transcript: Record<string, TranscriptEntry[]>; // keyed by jobId
  diffs: Record<string, DiffFileModel[]>; // keyed by jobId
  stories: Record<string, StoryResponse>; // keyed by jobId
  plans: Record<string, PlanStep[]>; // keyed by jobId
  timelines: Record<string, TimelineEntry[]>; // keyed by jobId
  activityTimelines: Record<string, ActivityTimelineState>; // keyed by jobId
  /** Accumulated streaming text for in-progress agent messages, keyed by
   * "${jobId}:${turnId}" (or "${jobId}:__default__" when turnId is absent).
   * Cleared when the complete agent message arrives for that turn. */
  streamingMessages: Record<string, string>;
  /** Accumulated streaming tool output for in-progress tool execution, keyed by
   * "${jobId}:${toolCallId}" (or "${jobId}:${toolName}" as fallback).
   * Cleared when the tool_call completion arrives. */
  streamingToolOutput: Record<string, string>;
  /** Accumulated streaming reasoning text for in-progress thinking, keyed by
   * "${jobId}:${turnId}" (or "${jobId}:__default__" when turnId is absent).
   * Cleared when the complete reasoning message arrives for that turn. */
  streamingReasoning: Record<string, string>;
  /** Monotonically-increasing counter per job, bumped on each telemetry_updated
   * SSE event. Components watching this trigger a telemetry re-fetch. */
  telemetryVersions: Record<string, number>; // keyed by jobId

  // Terminal state
  terminalDrawerOpen: boolean;
  terminalDrawerHeight: number;
  terminalSessions: Record<string, TerminalSession>;
  activeTerminalTab: string | null;

  // SDK + model catalogue (loaded once at app startup)
  sdks: SDKInfo[];
  defaultSdk: string | null;
  sdksLoading: boolean;
  modelsBySdk: Record<string, { value: string; label: string }[]>;
  defaultModelBySdk: Record<string, string | null>;
  modelsLoadingBySdk: Record<string, boolean>;

  // UI state
  connectionStatus: ConnectionStatus;
  reconnectAttempt: number;
  /** Plan item ID being hovered — used to highlight linked activities. */
  hoveredPlanItemId: string | null;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  setReconnectAttempt: (attempt: number) => void;
  /** Fetches SDK list + models for the default SDK. Called once on app mount. */
  initSdksAndModels: () => Promise<void>;
  /** Fetches models for a specific SDK (no-op if already loaded). */
  loadModelsForSdk: (sdkId: string) => Promise<void>;
  dispatchSSEEvent: (eventType: string, data: unknown) => void;
  applySnapshot: (jobs: JobSummary[], approvals: ApprovalRequest[]) => void;
  /** Bulk-apply a full job snapshot from the hydration endpoint. */
  hydrateJob: (snapshot: {
    job: JobSummary;
    logs: LogLine[];
    transcript: TranscriptEntry[];
    diff: DiffFileModel[];
    approvals: ApprovalRequest[];
    timeline: TimelineEntry[];
    steps?: Array<{ planStepId?: string; label: string; status: string; summary?: string; toolCount?: number; filesWritten?: string[]; durationMs?: number }>;
    turnSummaries?: Array<Record<string, unknown>>;
  }) => void;

  // Terminal actions
  toggleTerminalDrawer: () => void;
  setTerminalDrawerHeight: (height: number) => void;
  setActiveTerminalTab: (id: string) => void;
  addTerminalSession: (session: TerminalSession) => void;
  removeTerminalSession: (id: string) => void;
  createTerminalSession: (opts?: { cwd?: string; jobId?: string; label?: string }) => void;
  setHoveredPlanItemId: (id: string | null) => void;
  setStory: (jobId: string, story: StoryResponse) => void;
}

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

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

export const selectJobs = (state: AppState) => state.jobs;
export const selectConnectionStatus = (state: AppState) =>
  state.connectionStatus;
export const selectReconnectAttempt = (state: AppState) =>
  state.reconnectAttempt;
export const selectApprovals = (state: AppState) => state.approvals;

// Stable empty-array sentinels — MUST NOT be inline `?? []` because a new
// array literal is a new reference on every call, causing useSyncExternalStore
// to see a changed snapshot every render → infinite re-render loop (#185).
const EMPTY_LOGS: LogLine[] = [];
const EMPTY_TRANSCRIPT: TranscriptEntry[] = [];
const EMPTY_DIFFS: DiffFileModel[] = [];

export const selectJobLogs = (jobId: string) => (state: AppState) =>
  state.logs[jobId] ?? EMPTY_LOGS;
export const selectJobTranscript = (jobId: string) => (state: AppState) =>
  state.transcript[jobId] ?? EMPTY_TRANSCRIPT;
export const selectJobDiffs = (jobId: string) => (state: AppState) =>
  state.diffs[jobId] ?? EMPTY_DIFFS;

const EMPTY_STORY: StoryResponse | null = null;
export const selectJobStory = (jobId: string) => (state: AppState) =>
  state.stories[jobId] ?? EMPTY_STORY;

/** Select accumulated streaming tool output for a job, keyed by toolCallId. */
export const selectStreamingToolOutput = (jobId: string) => (state: AppState) => {
  const prefix = `${jobId}:`;
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(state.streamingToolOutput)) {
    if (key.startsWith(prefix)) {
      result[key.slice(prefix.length)] = value;
    }
  }
  return result;
};

/** Select accumulated streaming reasoning for a job, keyed by turnId. */
export const selectStreamingReasoning = (jobId: string) => (state: AppState) => {
  const prefix = `${jobId}:`;
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(state.streamingReasoning)) {
    if (key.startsWith(prefix)) {
      result[key.slice(prefix.length)] = value;
    }
  }
  return result;
};

// Per-column selectors — only recompute when jobs in that column change
function sortByUpdatedDesc(jobs: JobSummary[]): JobSummary[] {
  return jobs.sort(
    (a, b) =>
      new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
}

export const selectActiveJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(
    Object.values(state.jobs).filter(
      (j) => !j.archivedAt && (j.state === "preparing" || j.state === "queued" || j.state === "running"),
    ),
  );

/** Sign-off: everything that needs operator attention before archival.
 *  - waiting_for_approval
 *  - review (agent done, awaiting operator decision) — not archived
 *  - completed (finished but not yet archived)
 */
export const selectSignoffJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(
    Object.values(state.jobs).filter(
      (j) =>
        !j.archivedAt &&
        (j.state === "waiting_for_approval" ||
          j.state === "review" ||
          j.state === "completed"),
    ),
  );

/** Attention: failed jobs that haven't been archived. */
export const selectAttentionJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(
    Object.values(state.jobs).filter(
      (j) => !j.archivedAt && j.state === "failed",
    ),
  );

/** Archived jobs loaded into the store (for the history browser). */
export const selectArchivedJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(
    Object.values(state.jobs).filter((j) => !!j.archivedAt),
  );

/** Count of archived jobs known to the store (badge hint). */
export const selectArchivedCount = (state: AppState): number =>
  Object.values(state.jobs).filter((j) => !!j.archivedAt).length;

const EMPTY_TIMELINE: TimelineEntry[] = [];
export const selectJobTimeline = (jobId: string) => (state: AppState) =>
  state.timelines[jobId] ?? EMPTY_TIMELINE;

const EMPTY_PLAN: PlanStep[] = [];
export const selectJobPlan = (jobId: string) => (state: AppState) =>
  state.plans[jobId] ?? EMPTY_PLAN;

const EMPTY_ACTIVITY_TIMELINE: ActivityTimelineState = { activities: [] };
export const selectActivityTimeline = (jobId: string) => (state: AppState) =>
  state.activityTimelines[jobId] ?? EMPTY_ACTIVITY_TIMELINE;
export const selectHoveredPlanItemId = (state: AppState) => state.hoveredPlanItemId;

// Per-column selectors — only recompute when jobs in that column change

// Expose the store on window so Playwright capture scripts can inject
// test data (e.g. approval events) deterministically without relying on SSE timing.
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>)["__codeplane_store"] = useStore;
}

