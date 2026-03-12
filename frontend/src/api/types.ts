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
export type GlobalConfigResponse = components["schemas"]["GlobalConfigResponse"];

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

export interface TranscriptEntry {
  jobId: string;
  seq: number;
  timestamp: string;
  role: "agent" | "operator";
  content: string;
}

export interface ApprovalRequest {
  id: string;
  jobId: string;
  description: string;
  proposedAction: string | null;
  requestedAt: string;
  resolvedAt: string | null;
  resolution: string | null;
}

export interface JobStateChangedPayload {
  jobId: string;
  previousState: string | null;
  newState: string;
  timestamp: string;
}
