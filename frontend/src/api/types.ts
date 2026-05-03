/**
 * Friendly type aliases re-exported from the generated OpenAPI schema.
 *
 * All component code imports from this file, never from schema.d.ts directly.
 */

import type { components } from "./schema";

export type Job = components["schemas"]["JobResponse"];
export type JobState = Job["state"];
export type CreateJobRequest = components["schemas"]["CreateJobRequest"];
export type CreateJobResponse = components["schemas"]["CreateJobResponse"];
export type JobListResponse = components["schemas"]["JobListResponse"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type RegisterRepoRequest = components["schemas"]["RegisterRepoRequest"];
export type RegisterRepoResponse = components["schemas"]["RegisterRepoResponse"];
export type RepoListResponse = components["schemas"]["RepoListResponse"];
export type RepoDetailResponse = components["schemas"]["RepoDetailResponse"];
export type CompletionStrategy = "auto_merge" | "pr_only" | "manual";

export interface Settings {
  maxConcurrentJobs: number;
  autoPush: boolean;
  cleanupWorktree: boolean;
  deleteBranchAfterMerge: boolean;
  artifactRetentionDays: number;
  maxArtifactSizeMb: number;
  autoArchiveDays: number;
  maxTurns: number;
  verify: boolean;
  selfReview: boolean;
  verifyPrompt: string;
  selfReviewPrompt: string;
}

// SSE payload types — not in the OpenAPI schema since they're sent via SSE,
// so we define them here matching the backend CamelModel shapes.
export interface LogLine {
  jobId: string;
  seq: number;
  timestamp: string;
  level: "debug" | "info" | "warn" | "error";
  message: string;
  context: Record<string, unknown> | null;
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

// --- Action Policy batch types ---

export type ActionTier = "observe" | "checkpoint" | "gate";

export interface BatchAction {
  id: string;
  kind: string;
  toolName: string | null;
  path: string | null;
  command: string | null;
  tier: ActionTier;
  reversible: boolean;
  contained: boolean;
  reason: string;
  checkpointRef: string | null;
}

export interface BatchApprovalRequest {
  batchId: string;
  jobId: string;
  actions: BatchAction[];
  requestedAt: string;
}

export interface ResolveBatchRequest {
  batchId: string;
  resolution: "approved" | "rejected" | "partial" | "rollback";
  approvedIds?: string[];
  trustGrantId?: string;
}

export interface JobStateChangedPayload {
  jobId: string;
  previousState: string | null;
  newState: string;
  timestamp: string;
}

// --- Diff types ---

export type DiffLineType = "context" | "addition" | "deletion";
export type DiffFileStatus = "added" | "modified" | "deleted" | "renamed";

export interface DiffLineModel {
  type: DiffLineType;
  content: string;
}

export interface DiffHunkModel {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLineModel[];
}

export interface DiffFileModel {
  path: string;
  status: DiffFileStatus;
  additions: number;
  deletions: number;
  hunks: DiffHunkModel[];
  writeCount?: number | null;
  retryCount?: number | null;
}

// --- Motivation types for intent-annotated diff review ---

export interface HunkMotivation {
  editKey: string;
  title: string;
  why: string;
}

export interface FileMotivation {
  title: string;
  why: string;
  unmatchedEdits: HunkMotivation[];
}

export interface StepDiffResponse {
  stepId: string;
  diff: string;
  filesChanged: number;
  changedFiles: DiffFileModel[];
  stepContext?: string | null;
  fileMotivations?: Record<string, FileMotivation>;
  hunkMotivations?: Record<string, HunkMotivation>;
}

export interface DiffUpdatePayload {
  jobId: string;
  changedFiles: DiffFileModel[];
}

// --- Story types ---

export interface StoryBlock {
  type: "narrative" | "reference";
  // narrative fields
  text?: string | null;
  // reference fields
  spanId?: number | null;
  stepNumber?: number | null;
  stepTitle?: string | null;
  file?: string | null;
  why?: string | null;
  turnId?: string | null;
  editCount?: number | null;
}

export interface StoryResponse {
  jobId: string;
  blocks: StoryBlock[];
  cached: boolean;
  verbosity: "summary" | "standard" | "detailed";
}

// --- Review signal types ---

export interface TestCoModification {
  turnId: string | null;
  stepNumber: number | null;
  stepTitle: string | null;
  testFiles: string[];
  sourceFiles: string[];
}

export interface ReviewSignals {
  testCoModifications: TestCoModification[];
}

export interface ReviewComplexity {
  tier: "quick" | "standard" | "deep";
  signals: string[];
}

// --- Resolve types ---

export interface ResolveJobResponse {
  resolution: string;
  prUrl?: string | null;
  conflictFiles?: string[] | null;
  error?: string | null;
}

// --- Artifact types ---

export type ArtifactType = components["schemas"]["ArtifactType"];
export type ExecutionPhase = components["schemas"]["ExecutionPhase"];
export type GitMergeOutcome = components["schemas"]["GitMergeOutcome"];

export interface ArtifactResponse {
  id: string;
  jobId: string;
  name: string;
  type: ArtifactType;
  mimeType: string;
  sizeBytes: number;
  phase: ExecutionPhase;
  createdAt: string;
}

export interface ArtifactListResponse {
  items: ArtifactResponse[];
}

// --- Workspace types ---

export type WorkspaceEntryType = "file" | "directory";

export interface WorkspaceEntry {
  path: string;
  type: WorkspaceEntryType;
  sizeBytes: number | null;
}

export interface WorkspaceListResponse {
  items: WorkspaceEntry[];
  cursor: string | null;
  hasMore: boolean;
}

// --- SDK types ---

export interface SDKInfo {
  id: string;
  name: string;
  enabled: boolean;
  status: "ready" | "not_installed" | "not_configured";
  authenticated: boolean | null;
  hint: string;
}

export interface SDKListResponse {
  default: string;
  sdks: SDKInfo[];
}

// --- Naming suggestion types ---

export interface SuggestNamesResponse {
  title: string;
  description: string;
  branchName: string;
  worktreeName: string;
}
