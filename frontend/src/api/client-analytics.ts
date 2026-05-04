/**
 * Analytics API client module.
 *
 * Centralizes all analytics-related HTTP calls (scorecard, cost drivers,
 * model comparison, observations, fleet metrics, etc.).
 */

import { request } from "./client";

// ---------------------------------------------------------------------------
// Analytics Overview / Models / Tools / Repos / Jobs
// ---------------------------------------------------------------------------

export interface AnalyticsOverview {
  period: number;
  totalJobs: number;
  succeeded: number;
  review: number;
  completed: number;
  failed: number;
  cancelled: number;
  running: number;
  totalCostUsd: number;
  totalTokens: number;
  avgDurationMs: number;
  totalPremiumRequests: number;
  totalToolCalls: number;
  totalToolFailures: number;
  totalAgentErrors: number;
  totalToolErrors: number;
  toolSuccessRate: number;
  cacheHitRate: number;
  costTrend: { date: string; cost: number; jobs: number }[];
}

export interface AnalyticsModels {
  period: number;
  models: {
    model: string;
    sdk: string;
    job_count: number;
    total_cost_usd: number;
    total_tokens: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    avg_duration_ms: number;
    premium_requests: number;
    // Normalized metrics (from enhanced cost_by_model)
    total_turns?: number;
    total_tool_calls?: number;
    total_diff_lines?: number;
    cost_per_job?: number;
    cost_per_minute?: number;
    cost_per_turn?: number;
    cost_per_tool_call?: number;
    cost_per_diff_line?: number;
    cost_per_mtok?: number;
    cache_hit_rate?: number;
    [key: string]: unknown;
  }[];
}

export interface AnalyticsTools {
  period: number;
  tools: {
    name: string;
    count: number;
    avg_duration_ms: number;
    total_duration_ms: number;
    failure_count: number;
    p50_duration_ms: number;
    p95_duration_ms: number;
    p99_duration_ms: number;
  }[];
  toolMix?: {
    category: string;
    count: number;
    pct: number;
    totalDurationMs: number;
  }[];
}

export interface AnalyticsJobs {
  period: number;
  jobs: {
    job_id: string;
    sdk: string;
    model: string;
    repo: string;
    branch: string;
    status: string;
    created_at: string;
    completed_at: string | null;
    duration_ms: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    total_cost_usd: number;
    tool_call_count: number;
    llm_call_count: number;
    premium_requests: number;
  }[];
}

export interface AnalyticsRepos {
  period: number;
  repos: {
    repo: string;
    jobCount: number;
    succeeded: number;
    failed: number;
    totalCostUsd: number;
    totalTokens: number;
    toolCalls: number;
    avgDurationMs: number;
    premiumRequests: number;
  }[];
}

export function fetchAnalyticsOverview(period = 7): Promise<AnalyticsOverview> {
  return request(`/analytics/overview?period=${period}`);
}

export function fetchAnalyticsModels(period = 7): Promise<AnalyticsModels> {
  return request(`/analytics/models?period=${period}`);
}

export function fetchAnalyticsTools(period = 30): Promise<AnalyticsTools> {
  return request(`/analytics/tools?period=${period}`);
}

export function fetchAnalyticsRepos(period = 7): Promise<AnalyticsRepos> {
  return request(`/analytics/repos?period=${period}`);
}

// Model pricing — keyed by model name, null if not found
export interface ModelPricing {
  provider: string;
  input: number;       // $/MTok
  output: number;      // $/MTok
  cache_read: number;  // $/MTok
  cache_write: number; // $/MTok
  max_input_tokens: number;
  max_output_tokens: number;
}

export function fetchModelPricing(models: string[]): Promise<Record<string, ModelPricing | null>> {
  return request(`/analytics/pricing?models=${encodeURIComponent(models.join(","))}`);
}

export function fetchAnalyticsJobs(params?: {
  period?: number;
  sdk?: string;
  model?: string;
  status?: string;
  sort?: string;
  desc?: boolean;
  limit?: number;
  offset?: number;
}): Promise<AnalyticsJobs> {
  const sp = new URLSearchParams();
  if (params?.period) sp.set("period", String(params.period));
  if (params?.sdk) sp.set("sdk", params.sdk);
  if (params?.model) sp.set("model", params.model);
  if (params?.status) sp.set("status", params.status);
  if (params?.sort) sp.set("sort", params.sort);
  if (params?.desc !== undefined) sp.set("desc", String(params.desc));
  if (params?.limit) sp.set("limit", String(params.limit));
  if (params?.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  return request(`/analytics/jobs${qs ? `?${qs}` : ""}`);
}

// ---------------------------------------------------------------------------
// Cost Analytics API
// ---------------------------------------------------------------------------

export interface CostDriversResponse {
  jobId: string;
  dimensions: Record<string, CostAttributionBucket[]>;
}

export interface CostAttributionBucket {
  dimension: string;
  bucket: string;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  call_count: number;
  confidence: "exact" | "approximate";
}

export interface FleetCostDriversResponse {
  period: number;
  summary?: Array<CostAttributionBucket & {
    job_count?: number;
    avg_cost_per_job?: number;
    confidence?: "exact" | "approximate";
  }>;
  dimension?: string;
  buckets?: Array<CostAttributionBucket & {
    job_count?: number;
  }>;
}

// ---------------------------------------------------------------------------
// Latency attribution
// ---------------------------------------------------------------------------

export interface LatencyBucket {
  dimension: string;
  bucket: string;
  wallClockMs: number;
  sumDurationMs: number;
  spanCount: number;
  p50Ms: number;
  p95Ms: number;
  maxMs: number;
  pctOfTotal: number;
}

export interface FleetLatencyEntry {
  dimension: string;
  bucket: string;
  avgWallClockMs: number;
  avgSumDurationMs: number;
  totalSpanCount: number;
  jobCount: number;
  avgPctOfTotal: number;
}

export interface FleetLatencyDriversResponse {
  period: number;
  dimension?: string;
  summary: FleetLatencyEntry[];
  avgJobDurationMs: number;
  p50JobDurationMs: number;
  p95JobDurationMs: number;
}

export interface FileAccessResponse {
  jobId: string;
  stats: {
    total_accesses: number;
    unique_files: number;
    total_reads: number;
    total_writes: number;
    reread_count: number;
  };
  topFiles: Array<{
    file_path: string;
    access_count: number;
    read_count: number;
    write_count: number;
    job_count?: number;
  }>;
}

export interface TurnEconomicsResponse {
  jobId: string;
  totalTurns: number;
  peakTurnCostUsd: number;
  avgTurnCostUsd: number;
  costFirstHalfUsd: number;
  costSecondHalfUsd: number;
  turnCurve: CostAttributionBucket[];
}

export function fetchCostDrivers(jobId: string): Promise<CostDriversResponse> {
  return request(`/analytics/cost-drivers/${jobId}`);
}

export function fetchFleetCostDrivers(
  period = 30,
  dimension?: string,
): Promise<FleetCostDriversResponse> {
  const params = new URLSearchParams({ period: String(period) });
  if (dimension) params.set("dimension", dimension);
  return request(`/analytics/cost-drivers?${params}`);
}

export function fetchFleetLatencyDrivers(
  period = 30,
  dimension?: string,
): Promise<FleetLatencyDriversResponse> {
  const params = new URLSearchParams({ period: String(period) });
  if (dimension) params.set("dimension", dimension);
  return request(`/analytics/latency-drivers?${params}`);
}

export function fetchFileAccess(jobId: string): Promise<FileAccessResponse> {
  return request(`/analytics/file-access/${jobId}`);
}

export function fetchFleetFileAccess(
  period = 30,
): Promise<{ period: number; topFiles: FileAccessResponse["topFiles"] }> {
  return request(`/analytics/file-access?period=${period}`);
}

export function fetchTurnEconomics(jobId: string): Promise<TurnEconomicsResponse> {
  return request(`/analytics/turn-economics/${jobId}`);
}

// ---------------------------------------------------------------------------
// Shell command breakdown, retry cost, edit efficiency
// ---------------------------------------------------------------------------

export interface ShellCommandRow {
  command: string;
  call_count: number;
  total_cost_usd: number;
  avg_duration_ms: number;
  job_count: number;
}

export interface ShellCommandsResponse {
  period: number;
  commands: ShellCommandRow[];
}

export function fetchShellCommands(period = 30): Promise<ShellCommandsResponse> {
  return request(`/analytics/shell-commands?period=${period}`);
}

export interface RetryCostResponse {
  period: number;
  retryCostUsd: number;
  retryCount: number;
  totalSpans: number;
  totalCostUsd: number;
  retryPct: number;
}

export function fetchRetryCost(period = 30): Promise<RetryCostResponse> {
  return request(`/analytics/retry-cost?period=${period}`);
}

export interface EditEfficiencyRow {
  activity: string;
  editTurns: number;
  oneShotTurns: number;
  retries: number;
  oneShotRate: number;
  jobCount: number;
}

export interface EditEfficiencyResponse {
  period: number;
  categories: EditEfficiencyRow[];
}

export function fetchEditEfficiency(period = 30): Promise<EditEfficiencyResponse> {
  return request(`/analytics/edit-efficiency?period=${period}`);
}

// ---------------------------------------------------------------------------
// Scorecard / Redesigned Analytics
// ---------------------------------------------------------------------------

export interface ScorecardBudget {
  sdk: string;
  totalCostUsd: number;
  premiumRequests: number;
  jobCount: number;
  avgCostPerJob: number;
  avgDurationMs: number;
}

export interface ScorecardActivity {
  totalJobs: number;
  running: number;
  inReview: number;
  merged: number;
  prCreated: number;
  discarded: number;
  failed: number;
  cancelled: number;
}

export interface ScorecardResponse {
  period: number;
  activity: ScorecardActivity;
  budget: ScorecardBudget[];
  quotaJson: string | null;
  costTrend: { date: string; cost: number; jobs: number }[];
  dailySpendLimitUsd: number;
}

export interface ModelComparisonRow {
  model: string;
  sdk: string;
  jobCount: number;
  avgCost: number;
  avgDurationMs: number;
  totalCostUsd: number;
  premiumRequests: number;
  merged: number;
  prCreated: number;
  discarded: number;
  failed: number;
  avgVerifyTurns: number | null;
  verifyJobCount: number;
  avgDiffLines: number;
  cacheHitRate: number;
  costPerJob: number;
  costPerMinute: number;
  costPerTurn: number;
  costPerToolCall: number;
}

export interface ModelComparisonResponse {
  period: number;
  repo: string | null;
  models: ModelComparisonRow[];
}

export interface JobContextFlag {
  type: string;
  message: string;
}

export interface JobContextResponse {
  job: {
    cost: number;
    durationMs: number;
    diffLinesAdded: number;
    diffLinesRemoved: number;
    sdk: string;
    model: string;
    totalTurns: number;
    peakTurnCostUsd: number;
    avgTurnCostUsd: number;
    costFirstHalfUsd: number;
    costSecondHalfUsd: number;
  };
  repoAvg: {
    jobCount: number;
    avgCost: number;
    avgDurationMs: number;
    avgDiffLines: number;
  } | null;
  flags: JobContextFlag[];
}

export interface Observation {
  id: number;
  category: string;
  severity: string;
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
  job_count: number;
  total_waste_usd: number;
  first_seen_at: string;
  last_seen_at: string;
}

export interface ObservationsResponse {
  observations: Observation[];
}

export function fetchScorecard(period = 7): Promise<ScorecardResponse> {
  return request(`/analytics/scorecard?period=${period}`);
}

export function fetchModelComparison(
  period = 30,
  repo?: string,
): Promise<ModelComparisonResponse> {
  const params = new URLSearchParams({ period: String(period) });
  if (repo) params.set("repo", repo);
  return request(`/analytics/model-comparison?${params}`);
}

export function fetchJobContext(jobId: string): Promise<JobContextResponse> {
  return request(`/analytics/job-context/${jobId}`);
}

export function fetchObservations(
  category?: string,
  severity?: string,
): Promise<ObservationsResponse> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (severity) params.set("severity", severity);
  const qs = params.toString();
  return request(`/analytics/observations${qs ? `?${qs}` : ""}`);
}

export function dismissObservation(observationId: number): Promise<{ status: string }> {
  return request(`/analytics/observations/${observationId}/dismiss`, { method: "POST" });
}
