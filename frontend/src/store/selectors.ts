/**
 * Zustand store selectors — stable selector functions for components.
 *
 * Using named selectors (instead of inline arrow functions in components)
 * prevents unnecessary re-renders and makes state dependencies explicit.
 */

import type { DiffFileModel, StoryResponse } from "../api/types";
import type {
  MultiSessionResponse,
  ReviewStoryResponse as StructuralReviewStoryResponse,
} from "../api/client";
import type {
  AppState,
  JobSummary,
  LogLine,
  TranscriptEntry,
  PlanStep,
  TimelineEntry,
  ActivityTimelineState,
} from "./types";

// Stable empty-array sentinels — MUST NOT be inline `?? []` because a new
// array literal is a new reference on every call, causing useSyncExternalStore
// to see a changed snapshot every render → infinite re-render loop (#185).
const EMPTY_LOGS: LogLine[] = [];
const EMPTY_TRANSCRIPT: TranscriptEntry[] = [];
const EMPTY_DIFFS: DiffFileModel[] = [];

export const selectJobs = (state: AppState) => state.jobs;
export const selectConnectionStatus = (state: AppState) =>
  state.connectionStatus;
export const selectReconnectAttempt = (state: AppState) =>
  state.reconnectAttempt;
export const selectApprovals = (state: AppState) => state.approvals;
export const selectBatchApprovals = (state: AppState) => state.batchApprovals;

export const selectJobLogs = (jobId: string) => (state: AppState) =>
  state.logs[jobId] ?? EMPTY_LOGS;
export const selectJobTranscript = (jobId: string) => (state: AppState) =>
  state.transcript[jobId] ?? EMPTY_TRANSCRIPT;
export const selectJobDiffs = (jobId: string) => (state: AppState) =>
  state.diffs[jobId] ?? EMPTY_DIFFS;

const EMPTY_STORY: StoryResponse | null = null;
export const selectJobStory = (jobId: string) => (state: AppState) =>
  state.stories[jobId] ?? EMPTY_STORY;

// Structural analysis selectors
export const selectMultiSession = (jobId: string) => (state: AppState): MultiSessionResponse | null =>
  state.multiSessions[jobId] ?? null;
export const selectReviewStory = (jobId: string) => (state: AppState): StructuralReviewStoryResponse | null =>
  state.reviewStories[jobId] ?? null;

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

// Classifier predicates (AD-1: one shared job-status classifier, reused by the flat
// cross-repo selectors below, the repo-scoped `*ForRepo` variants used by RepoBoard,
// and the mobile segmented list — never re-implemented at a second call site.
// These are exported precisely so no caller has an excuse to re-derive them.)
//
// AD-1a (totality): the four predicates below partition the ENTIRE
// state × resolution space of an unarchived job into exactly one column — every
// cell maps to one bucket, none to zero, none to two. A job that matches no
// predicate is invisible on the board, and (because History lists archived jobs
// only) invisible in the whole UI. Regression-guarded by selectors.test.ts, which
// enumerates all 8 states × 6 resolutions. If you add a JobState or Resolution,
// extend a predicate here or that test fails by design.
export function isActiveJob(j: JobSummary): boolean {
  return !j.archivedAt && (j.state === "preparing" || j.state === "queued" || j.state === "running");
}

/** Sign-off: everything that needs an operator decision before it can finish.
 *  - waiting_for_approval
 *  - review (agent done, awaiting operator decision) — not archived
 *  - completed but still unresolved (operator hasn't decided yet)
 *  - completed with a `conflict` resolution: terminal in name only. The work
 *    cannot land until a human resolves the conflict, so it belongs with the
 *    work that needs input, NOT in Done.
 */
export function isSignoffJob(j: JobSummary): boolean {
  return (
    !j.archivedAt &&
    (j.state === "waiting_for_approval" ||
      j.state === "review" ||
      (j.state === "completed" &&
        (!j.resolution || j.resolution === "unresolved" || j.resolution === "conflict")))
  );
}

/** Attention: failed jobs that haven't been archived. */
export function isAttentionJob(j: JobSummary): boolean {
  return !j.archivedAt && j.state === "failed";
}

/** Done: work that reached a real conclusion and owes the operator nothing.
 *
 *  Done is a BOARD column, not a synonym for archived. Landed work stays visible
 *  here until the operator archives it (or the configured Auto-archive window
 *  elapses). Nothing leaves the board because an agent merged something — it
 *  leaves because the operator decided it should.
 *
 *  Covers: completed+merged / +pr_created / +discarded, and every `canceled` job.
 *  `discarded` and `canceled` are conclusions the operator already made, so they
 *  need no further input — but they still get a visible resting place rather than
 *  silently vanishing.
 */
export function isDoneJob(j: JobSummary): boolean {
  return (
    !j.archivedAt &&
    (j.state === "canceled" ||
      (j.state === "completed" &&
        (j.resolution === "merged" ||
          j.resolution === "pr_created" ||
          j.resolution === "discarded")))
  );
}

export const selectActiveJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter(isActiveJob));

export const selectSignoffJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter(isSignoffJob));

export const selectAttentionJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter(isAttentionJob));

export const selectDoneJobs = (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter(isDoneJob));

// Repo-scoped variants (CAP-1 / Story 2.3, RepoBoard.tsx). AD-2: repo scoping travels
// via the URL route param — `repoPath` is passed in by the caller, not read from
// store or client-only state. A single-repo Project reduces to `job.repo === repoPath`.
export const selectActiveJobsForRepo = (repoPath: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.repo === repoPath && isActiveJob(j)));

export const selectSignoffJobsForRepo = (repoPath: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.repo === repoPath && isSignoffJob(j)));

export const selectAttentionJobsForRepo = (repoPath: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.repo === repoPath && isAttentionJob(j)));

export const selectDoneJobsForRepo = (repoPath: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.repo === repoPath && isDoneJob(j)));

// Project-scoped variants — true multi-repo aggregation across every member
// repo of a Project (not just a single reduced repo path). Used by the
// project-identity-routed board so a multi-repo Project's board genuinely
// shows jobs from all its member repos, not only the first one.
//
// Every Job has an owning Project (AD-5) — there is no legacy "no project"
// state to fall back to a repo-path match for, so these match on
// `projectId` alone.
export const selectActiveJobsForProject = (projectId: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.projectId === projectId && isActiveJob(j)));

export const selectSignoffJobsForProject = (projectId: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.projectId === projectId && isSignoffJob(j)));

export const selectAttentionJobsForProject = (projectId: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.projectId === projectId && isAttentionJob(j)));

export const selectDoneJobsForProject = (projectId: string) => (state: AppState): JobSummary[] =>
  sortByUpdatedDesc(Object.values(state.jobs).filter((j) => j.projectId === projectId && isDoneJob(j)));

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

const EMPTY_SECONDARY_SESSIONS: Record<string, import("./types").SecondarySession> = {};
export const selectSecondarySessions = (jobId: string) => (state: AppState) =>
  state.secondarySessions[jobId] ?? EMPTY_SECONDARY_SESSIONS;

const EMPTY_CONTEXT_HANDOFFS: import("./types").ContextHandoff[] = [];
export const selectContextHandoffs = (jobId: string) => (state: AppState) =>
  state.contextHandoffs[jobId] ?? EMPTY_CONTEXT_HANDOFFS;
