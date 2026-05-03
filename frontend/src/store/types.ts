/**
 * Store type definitions — domain models used across the application.
 *
 * These mirror the CamelModel shapes from the backend. Components, hooks,
 * and services import these types to stay in sync with the store schema.
 */

import type { DiffFileModel, SDKInfo, StoryResponse } from "../api/types";

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
  totalCostUsd?: number | null;
  totalTokens?: number | null;
  inputTokens?: number | null;
  outputTokens?: number | null;
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

/** A batch of gate-tier actions awaiting operator approval. */
export interface BatchApprovalAction {
  id: string;
  kind: string;
  tier: string;
  reason: string;
  reversible: boolean;
  contained: boolean;
  checkpointRef: string | null;
  description: string;
}

export interface BatchApproval {
  batchId: string;
  jobId: string;
  actions: BatchApprovalAction[];
  summary: string;
  requestedAt: string;
  resolvedAt: string | null;
  resolution: string | null;
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
  /** Highest action policy tier seen during this turn. */
  tier?: "observe" | "checkpoint" | "gate" | null;
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
  batchApprovals: Record<string, BatchApproval>; // keyed by batchId
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
  /** Incremented when policy settings change via SSE — triggers re-fetch. */
  policySettingsVersion: number;

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
