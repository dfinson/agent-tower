/**
 * REST API client module.
 *
 * Centralizes all HTTP calls to the backend. Components should import
 * functions from here rather than calling fetch() directly.
 */

import type {
  ArtifactListResponse,
  CreateJobRequest,
  CreateJobResponse,
  ApprovalRequest,
  DiffFileModel,
  HealthResponse,
  Job,
  JobListResponse,
  RepoDetailResponse,
  RepoListResponse,
  SDKListResponse,
  Settings,
  WorkspaceListResponse,
} from "./types";

const BASE = "/api";
const REQUEST_TIMEOUT_MS = 30_000;
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** Strip HTML tags to prevent XSS when error details are rendered in UI. */
function sanitize(text: string): string {
  return text.replace(/<[^>]*>/g, "");
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (init?.body) {
    headers["Content-Type"] = "application/json";
  }

  let lastError: unknown;
  const isIdempotent = !init?.method || init.method === "GET" || init.method === "HEAD";

  for (let attempt = 0; attempt <= (isIdempotent ? MAX_RETRIES : 0); attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, RETRY_DELAY_MS * attempt));
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const res = await fetch(`${BASE}${path}`, {
        ...init,
        headers: { ...headers, ...init?.headers },
        signal: init?.signal ?? controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) {
        // Don't retry client errors (4xx)
        if (res.status >= 400 && res.status < 500) {
          throw await buildApiError(res);
        }
        // Retry server errors (5xx) for idempotent requests
        lastError = await buildApiError(res);
        if (attempt < (isIdempotent ? MAX_RETRIES : 0)) continue;
        throw lastError;
      }
      if (res.status === 204) return undefined as T;
      return res.json() as Promise<T>;
    } catch (e) {
      clearTimeout(timeout);
      if (e instanceof ApiError) throw e;
      if ((e as Error).name === "AbortError") {
        throw new ApiError(0, "Request timed out");
      }
      lastError = e;
      if (attempt < (isIdempotent ? MAX_RETRIES : 0)) continue;
      throw e;
    }
  }
  throw lastError;
}

async function buildApiError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  let detail: string;
  if (body == null) {
    detail = res.statusText || `HTTP ${res.status}`;
  } else if (typeof body.detail === "string") {
    detail = sanitize(body.detail);
  } else if (Array.isArray(body.detail)) {
    detail = body.detail
      .map((e: { loc?: string[]; msg?: string }) =>
        [e.loc?.slice(1).join("."), e.msg].filter(Boolean).join(": "),
      )
      .join("; ");
  } else {
    detail = res.statusText || `HTTP ${res.status}`;
  }
  return new ApiError(res.status, detail);
}

// --- Health ---

export function fetchHealth(): Promise<HealthResponse> {
  return request("/health");
}

export interface SisterSessionMetrics {
  global: {
    totalCalls: number;
    avgLatencyMs: number;
    activeJobs: number;
    poolSize: number;
    warmTokens: number;
  };
  jobs: Record<string, {
    callCount: number;
    avgLatencyMs: number;
    totalLatencyMs: number;
    inputTokens: number;
    outputTokens: number;
    costUsd: number;
  }>;
}

export function fetchSisterSessionMetrics(): Promise<SisterSessionMetrics> {
  return request("/sister-sessions/metrics");
}

// --- Jobs ---

export function fetchJobs(params?: {
  state?: string;
  limit?: number;
  cursor?: string;
  archived?: boolean;
}): Promise<JobListResponse> {
  const qs = new URLSearchParams();
  if (params?.state) qs.set("state", params.state);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  if (params?.archived !== undefined) qs.set("archived", String(params.archived));
  const query = qs.toString();
  return request(`/jobs${query ? `?${query}` : ""}`);
}

export function fetchJob(jobId: string): Promise<Job> {
  return request(`/jobs/${encodeURIComponent(jobId)}`);
}

export function fetchJobLogs(jobId: string, level: string = "debug", limit = 2000): Promise<import("../store").LogLine[]> {
  return request<{ items: import("../store").LogLine[] }>(`/jobs/${encodeURIComponent(jobId)}/logs?level=${encodeURIComponent(level)}&limit=${limit}`).then((r) => r.items);
}

export function fetchJobTranscript(jobId: string, limit = 2000): Promise<import("../store").TranscriptEntry[]> {
  return request<{ items: import("../store").TranscriptEntry[] }>(`/jobs/${encodeURIComponent(jobId)}/transcript?limit=${limit}`).then((r) => r.items);
}

export function fetchJobDiff(jobId: string): Promise<DiffFileModel[]> {
  return request<{ items: DiffFileModel[] }>(`/jobs/${encodeURIComponent(jobId)}/diff`).then((r) => r.items);
}

/** Fetch the diff for a single step/turn (uses turn_id as the step lookup key). */
export function fetchStepDiff(jobId: string, turnId: string): Promise<import("../api/types").StepDiffResponse> {
  return request(`/jobs/${encodeURIComponent(jobId)}/steps/${encodeURIComponent(turnId)}/diff`);
}

export function fetchJobTimeline(jobId: string, limit = 200): Promise<import("../store").TimelineEntry[]> {
  return request<{ items: Array<{ headline: string; headlinePast: string; summary?: string; timestamp: string }> }>(
    `/jobs/${encodeURIComponent(jobId)}/timeline?limit=${limit}`,
  ).then((r) =>
    r.items.map((e) => ({
      headline: e.headline,
      headlinePast: e.headlinePast,
      summary: e.summary ?? "",
      timestamp: e.timestamp,
      active: false,
    })),
  );
}

export function fetchTranscriptSearch(
  jobId: string,
  q: string,
  opts?: { roles?: string[]; stepId?: string; limit?: number },
): Promise<Array<{ seq: number; role: string; content: string; toolName: string | null; stepId: string | null; stepNumber: number | null; timestamp: string }>> {
  const params = new URLSearchParams({ q });
  if (opts?.roles) opts.roles.forEach((r) => params.append("roles", r));
  if (opts?.stepId) params.set("step_id", opts.stepId);
  if (opts?.limit) params.set("limit", String(opts.limit));
  return request<{ items: Array<{ seq: number; role: string; content: string; toolName: string | null; stepId: string | null; stepNumber: number | null; timestamp: string }> }>(`/jobs/${encodeURIComponent(jobId)}/transcript/search?${params}`).then((r) => r.items);
}

export function restoreToSha(jobId: string, sha: string): Promise<{ restored: boolean; sha: string }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sha }),
  });
}

/** Full state hydration for a single job — used after reconnect or page refresh. */
export function fetchJobSnapshot(jobId: string): Promise<{
  job: import("../store").JobSummary;
  logs: import("../store").LogLine[];
  transcript: import("../store").TranscriptEntry[];
  diff: DiffFileModel[];
  approvals: import("../store").ApprovalRequest[];
  timeline: import("../store").TimelineEntry[];
  steps?: Array<{ planStepId?: string; label: string; status: string; summary?: string; toolCount?: number; filesWritten?: string[]; durationMs?: number }>;
  turnSummaries?: Array<Record<string, unknown>>;
}> {
  return request(`/jobs/${encodeURIComponent(jobId)}/snapshot`);
}

export function createJob(body: CreateJobRequest): Promise<CreateJobResponse> {
  return request("/jobs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function warmUtilitySession(): Promise<string> {
  const resp: { sessionToken: string } = await request("/utility-sessions/warm", {
    method: "POST",
  });
  return resp.sessionToken;
}

export async function releaseUtilitySession(token: string): Promise<void> {
  await request(`/utility-sessions/${encodeURIComponent(token)}`, {
    method: "DELETE",
  });
}

export function suggestNames(prompt: string): Promise<import("./types").SuggestNamesResponse> {
  return request("/jobs/suggest-names", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function cancelJob(jobId: string): Promise<Job> {
  return request(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

export function interruptJob(jobId: string): Promise<void> {
  return request(`/jobs/${encodeURIComponent(jobId)}/interrupt`, {
    method: "POST",
  });
}

export function rerunJob(jobId: string): Promise<CreateJobResponse> {
  return request(`/jobs/${encodeURIComponent(jobId)}/rerun`, {
    method: "POST",
  });
}

export function fetchModels(sdk?: string): Promise<{ id?: string; name?: string; [key: string]: unknown }[]> {
  const qs = sdk ? `?sdk=${encodeURIComponent(sdk)}` : "";
  return request<{ items: { id?: string; name?: string; [key: string]: unknown }[] }>(`/models${qs}`).then((r) => r.items);
}

export function fetchSDKs(): Promise<SDKListResponse> {
  return request("/sdks");
}

export function fetchJobTelemetry(jobId: string): Promise<{
  available: boolean;
  jobId: string;
  model?: string;
  mainModel?: string;
  durationMs?: number;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  totalCost?: number;
  contextWindowSize?: number;
  currentContextTokens?: number;
  contextUtilization?: number;
  compactions?: number;
  tokensCompacted?: number;
  toolCallCount?: number;
  totalToolDurationMs?: number;
  toolCalls?: { name: string; durationMs: number; success: boolean }[];
  llmCallCount?: number;
  totalLlmDurationMs?: number;
  llmCalls?: { model: string; inputTokens: number; outputTokens: number; cacheReadTokens: number; cacheWriteTokens: number; cost: number; durationMs: number; isSubagent: boolean }[];
  approvalCount?: number;
  totalApprovalWaitMs?: number;
  agentMessages?: number;
  operatorMessages?: number;
  premiumRequests?: number;
  quotaSnapshots?: Record<string, {
    usedRequests: number;
    entitlementRequests: number;
    remainingPercentage: number;
    overage: number;
    overageAllowed: boolean;
    isUnlimited: boolean;
    usageAllowedWithExhaustedQuota: boolean;
    resetDate: string;
  }>;
  costDrivers?: {
    activity?: Array<{
      dimension: string;
      bucket: string;
      costUsd: number;
      inputTokens: number;
      outputTokens: number;
      callCount: number;
    }>;
    phase?: Array<{
      dimension: string;
      bucket: string;
      costUsd: number;
      inputTokens: number;
      outputTokens: number;
      callCount: number;
    }>;
    editEfficiency?: Array<{
      dimension: string;
      bucket: string;
      costUsd: number;
      inputTokens: number;
      outputTokens: number;
      callCount: number;
    }>;
  };
  turnEconomics?: {
    totalTurns: number;
    peakTurnCostUsd: number;
    avgTurnCostUsd: number;
    costFirstHalfUsd: number;
    costSecondHalfUsd: number;
    turnCurve: Array<{
      dimension: string;
      bucket: string;
      costUsd: number;
      inputTokens: number;
      outputTokens: number;
      callCount: number;
      activity?: string;
      intent?: string;
      actions?: string[];
    }>;
  };
  fileAccess?: {
    stats: {
      totalAccesses: number;
      uniqueFiles: number;
      totalReads: number;
      totalWrites: number;
      rereadCount: number;
    };
    topFiles: Array<{
      filePath: string;
      accessCount: number;
      readCount: number;
      writeCount: number;
    }>;
  };
}> {
  return request(`/jobs/${encodeURIComponent(jobId)}/telemetry`);
}

// --- Repos ---

export function fetchRepos(): Promise<RepoListResponse> {
  return request("/settings/repos");
}

export function fetchRepoDetail(repoPath: string): Promise<RepoDetailResponse> {
  return request(`/settings/repos/${encodeURIComponent(repoPath)}`);
}

export function registerRepo(source: string, cloneTo?: string): Promise<{ path: string; source: string; cloned: boolean }> {
  return request("/settings/repos", {
    method: "POST",
    body: JSON.stringify({ source, clone_to: cloneTo }),
  });
}

export function createRepo(path: string, name?: string): Promise<{ path: string; name: string }> {
  return request("/settings/repos/create", {
    method: "POST",
    body: JSON.stringify({ path, name: name || undefined }),
  });
}

export function unregisterRepo(repoPath: string): Promise<void> {
  return request(`/settings/repos/${encodeURIComponent(repoPath)}`, {
    method: "DELETE",
  });
}

export function browseDirectories(path?: string): Promise<{
  current: string;
  parent: string | null;
  items: { name: string; path: string; isGitRepo: boolean }[];
}> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  return request(`/settings/browse${qs}`);
}

// --- Settings ---

export function fetchSettings(): Promise<Settings> {
  return request("/settings");
}

export function updateSettings(settings: Partial<Settings>): Promise<Settings> {
  return request("/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

// --- Artifacts ---

export function fetchArtifacts(jobId: string): Promise<ArtifactListResponse> {
  return request(`/jobs/${encodeURIComponent(jobId)}/artifacts`);
}

export function downloadArtifactUrl(artifactId: string): string {
  return `${BASE}/artifacts/${encodeURIComponent(artifactId)}`;
}

export async function fetchArtifactContent(artifactId: string): Promise<unknown> {
  const url = downloadArtifactUrl(artifactId);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`artifact fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchArtifactText(artifactId: string): Promise<string> {
  const url = downloadArtifactUrl(artifactId);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`artifact fetch failed: ${res.status}`);
  return res.text();
}

// --- Workspace ---

export function fetchWorkspaceFiles(
  jobId: string,
  params?: { path?: string; cursor?: string; limit?: number },
): Promise<WorkspaceListResponse> {
  const qs = new URLSearchParams();
  if (params?.path) qs.set("path", params.path);
  if (params?.cursor) qs.set("cursor", params.cursor);
  if (params?.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return request(`/jobs/${encodeURIComponent(jobId)}/workspace${query ? `?${query}` : ""}`);
}

export function fetchWorkspaceFile(
  jobId: string,
  path: string,
): Promise<{ path: string; content: string }> {
  const qs = new URLSearchParams({ path });
  return request(`/jobs/${encodeURIComponent(jobId)}/workspace/file?${qs.toString()}`);
}

export function workspaceFileRawUrl(jobId: string, path: string): string {
  const qs = new URLSearchParams({ path });
  return `${BASE}/jobs/${encodeURIComponent(jobId)}/workspace/file/raw?${qs.toString()}`;
}

// --- Approvals ---

export function fetchApprovals(jobId: string): Promise<ApprovalRequest[]> {
  return request<{ items: ApprovalRequest[] }>(`/jobs/${encodeURIComponent(jobId)}/approvals`).then((r) => r.items);
}

export function resolveApproval(
  approvalId: string,
  resolution: "approved" | "rejected",
): Promise<ApprovalRequest> {
  return request(`/approvals/${encodeURIComponent(approvalId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ resolution }),
  });
}

export function trustJob(jobId: string): Promise<{ resolved: number }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/approvals/trust`, {
    method: "POST",
  });
}

// --- Action Policy Batches ---

export function resolveBatch(
  jobId: string,
  batchId: string,
  resolution: "approved" | "rejected" | "partial" | "rollback",
  approvedIds?: string[],
  trustGrantId?: string,
): Promise<{ resolved: boolean }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/batches/resolve`, {
    method: "POST",
    body: JSON.stringify({ batchId, resolution, approvedIds, trustGrantId }),
  });
}

// --- Policy Settings ---

export interface PolicyConfig {
  preset: string;
  batchWindowSeconds: number;
}

export interface PolicyState {
  config: PolicyConfig;
  pathRules: Array<{ id: string; pathPattern: string; tier: string; reason: string; createdAt: string }>;
  actionRules: Array<{ id: string; matchPattern: string; tier: string; reason: string; createdAt: string }>;
  costRules: Array<{ id: string; condition: string; promoteTo: string; thresholdValue: number | null; reason: string; createdAt: string }>;
  mcpServers: Array<{ name: string; command: string; contained: boolean; reversible: boolean; trusted: boolean; createdAt: string }>;
  trustGrants: Array<{ id: string; kinds: string[]; pathPattern: string | null; commandPattern: string | null; mcpServer: string | null; jobId: string | null; expiresAt: string | null; reason: string; createdAt: string }>;
}

export function fetchPolicySettings(): Promise<PolicyState> {
  return request("/settings/policy");
}

export function updatePolicyPreset(preset: string): Promise<PolicyConfig> {
  return request("/settings/policy/preset", {
    method: "PUT",
    body: JSON.stringify({ preset }),
  });
}

export function updatePolicyConfig(config: Partial<PolicyConfig>): Promise<PolicyConfig> {
  return request("/settings/policy/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export function createPathRule(rule: { pathPattern: string; tier: string; reason: string }): Promise<unknown> {
  return request("/settings/policy/path-rules", {
    method: "POST",
    body: JSON.stringify(rule),
  });
}

export function deletePathRule(id: string): Promise<void> {
  return request(`/settings/policy/path-rules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function createActionRule(rule: { matchPattern: string; tier: string; reason: string }): Promise<unknown> {
  return request("/settings/policy/action-rules", {
    method: "POST",
    body: JSON.stringify(rule),
  });
}

export function deleteActionRule(id: string): Promise<void> {
  return request(`/settings/policy/action-rules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function createCostRule(rule: { condition: string; promoteTo: string; thresholdValue: number | null; reason: string }): Promise<unknown> {
  return request("/settings/policy/cost-rules", {
    method: "POST",
    body: JSON.stringify(rule),
  });
}

export function deleteCostRule(id: string): Promise<void> {
  return request(`/settings/policy/cost-rules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function deleteTrustGrant(id: string): Promise<void> {
  return request(`/settings/policy/trust-grants/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

// --- Operator Messages ---

export function sendOperatorMessage(
  jobId: string,
  content: string,
): Promise<{ seq: number; timestamp: string }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function pauseJob(jobId: string): Promise<void> {
  return request(`/jobs/${encodeURIComponent(jobId)}/pause`, {
    method: "POST",
  });
}

export function continueJob(
  jobId: string,
  instruction: string,
): Promise<{ id: string; state: string; branch: string | null; worktreePath: string | null; createdAt: string }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/continue`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

export function resumeJob(
  jobId: string,
  instruction?: string,
): Promise<{ id: string; state: string; branch: string | null; worktreePath: string | null; createdAt: string; updatedAt: string }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/resume`, {
    method: "POST",
    body: JSON.stringify(instruction?.trim() ? { instruction } : {}),
  });
}

// --- Job Resolution ---

export function resolveJob(
  jobId: string,
  action: "merge" | "smart_merge" | "create_pr" | "discard" | "agent_merge",
): Promise<{ resolution: string; prUrl?: string | null; conflictFiles?: string[] | null; error?: string | null }> {
  return request(`/jobs/${encodeURIComponent(jobId)}/resolve`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function archiveJob(jobId: string): Promise<void> {
  return request(`/jobs/${encodeURIComponent(jobId)}/archive`, {
    method: "POST",
  });
}

// --- Voice ---

export async function transcribeAudio(audio: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", audio, "recording.webm");
  const res = await fetch(`${BASE}/voice/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body != null && typeof body.detail === "string"
      ? body.detail
      : res.statusText || `HTTP ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as { text: string };
  return data.text;
}

export async function createTerminalSession(opts: {
  cwd?: string | null;
  jobId?: string | null;
  promptLabel?: string | null;
}): Promise<{ id: string; cwd: string; jobId?: string | null }> {
  return request<{ id: string; cwd: string; jobId?: string | null }>("/terminal/sessions", {
    method: "POST",
    body: JSON.stringify({
      cwd: opts.cwd ?? null,
      jobId: opts.jobId ?? null,
      promptLabel: opts.promptLabel ?? null,
    }),
  });
}

export async function deleteTerminalSession(id: string): Promise<void> {
  await request<unknown>(`/terminal/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export interface ObserverTerminalInfo {
  id: string;
  jobId: string | null;
  observer: boolean;
}

export async function fetchObserverTerminal(
  jobId: string,
): Promise<ObserverTerminalInfo | null> {
  try {
    return await request<ObserverTerminalInfo>(
      `/terminal/observer/${encodeURIComponent(jobId)}`,
    );
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Push notifications
// ---------------------------------------------------------------------------

export function fetchVapidKey(): Promise<{ publicKey: string }> {
  return request("/notifications/vapid-key");
}

export function subscribePush(subscription: PushSubscriptionJSON): Promise<void> {
  return request("/notifications/subscribe", {
    method: "POST",
    body: JSON.stringify(subscription),
  });
}

export function unsubscribePush(endpoint: string): Promise<void> {
  return request("/notifications/unsubscribe", {
    method: "POST",
    body: JSON.stringify({ endpoint }),
  });
}

// ---------------------------------------------------------------------------
// Job sharing
// ---------------------------------------------------------------------------

export function createShareLink(jobId: string): Promise<{ token: string; jobId: string; url: string }> {
  return request(`/jobs/${jobId}/share`, { method: "POST" });
}

export function fetchSharedSnapshot(token: string): Promise<{
  job: import("../store").JobSummary;
  logs: import("../store").LogLine[];
  transcript: import("../store").TranscriptEntry[];
  diff: DiffFileModel[];
  approvals: import("../store").ApprovalRequest[];
  timeline: import("../store").TimelineEntry[];
  turnSummaries?: Array<Record<string, unknown>>;
}> {
  return request(`/share/${encodeURIComponent(token)}/snapshot`);
}

export function fetchSharedTelemetry(token: string): Promise<Record<string, unknown>> {
  return request(`/share/${encodeURIComponent(token)}/telemetry`);
}

// ---------------------------------------------------------------------------
// Job Story
// ---------------------------------------------------------------------------

export function fetchJobStory(
  jobId: string,
  regenerate = false,
  verbosity: "summary" | "standard" | "detailed" = "standard",
): Promise<import("./types").StoryResponse> {
  const params = new URLSearchParams();
  if (regenerate) params.set("regenerate", "true");
  if (verbosity !== "standard") params.set("verbosity", verbosity);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return request(`/jobs/${encodeURIComponent(jobId)}/story${qs}`);
}

export { ApiError };

// Re-export analytics module for backward compatibility
export * from "./client-analytics";
