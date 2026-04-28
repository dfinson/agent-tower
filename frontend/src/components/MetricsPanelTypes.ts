// ---------------------------------------------------------------------------
// Types shared across MetricsPanel and its section sub-components.
// ---------------------------------------------------------------------------

export interface ToolCall {
  name: string;
  durationMs: number;
  success: boolean;
  offsetSec?: number;
}

export interface LLMCall {
  model: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  cost?: number;
  durationMs: number;
  offsetSec?: number;
  isSubagent: boolean;
  callCount?: number;
}

export interface TelemetryData {
  available: boolean;
  sdk?: string;
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
  toolCalls?: ToolCall[];
  llmCallCount?: number;
  totalLlmDurationMs?: number;
  llmCalls?: LLMCall[];
  approvalCount?: number;
  totalApprovalWaitMs?: number;
  agentMessages?: number;
  operatorMessages?: number;
  premiumRequests?: number;
  quotaSnapshots?: Record<string, QuotaSnapshotData>;
  costDrivers?: CostDriversData;
  turnEconomics?: TurnEconomicsData;
  fileAccess?: FileAccessData;
  reviewComplexity?: { tier: string; signals: string[] };
  reviewSignals?: { testCoModifications: unknown[] };
}

export interface CostDriverBucket {
  dimension: string;
  bucket: string;
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  callCount: number;
}

export interface CostDriversData {
  activity?: CostDriverBucket[];
  phase?: CostDriverBucket[];
}

export interface TurnEconomicsData {
  totalTurns: number;
  peakTurnCostUsd: number;
  avgTurnCostUsd: number;
  costFirstHalfUsd: number;
  costSecondHalfUsd: number;
  turnCurve: CostDriverBucket[];
}

export interface FileAccessData {
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
}

export interface QuotaSnapshotData {
  usedRequests: number;
  entitlementRequests: number;
  remainingPercentage: number;
  overage: number;
  overageAllowed: boolean;
  isUnlimited: boolean;
  usageAllowedWithExhaustedQuota: boolean;
  resetDate: string;
}

export interface SummaryAccomplished {
  what: string;
  files_affected?: string[];
}

export interface SummaryInProgress {
  description: string;
  file?: string;
}

export interface SummaryVerification {
  tests_run: boolean;
  tests_passed: boolean | null;
  build_run: boolean;
  build_passed: boolean | null;
}

export interface SessionSummaryJson {
  session_number?: number;
  accomplished?: SummaryAccomplished[];
  in_progress?: SummaryInProgress[] | null;
  resume_instructions?: string;
  verification_state?: SummaryVerification | null;
}

export interface SessionCheckpoint {
  sessionNumber: number;
  artifactId: string;
  createdAt: string;
  summary: SessionSummaryJson | null;
}

export type SortField = "name" | "count" | "avgMs" | "totalMs" | "fails";
export type SortDir = "asc" | "desc";

export interface ToolAggregate {
  name: string;
  count: number;
  totalMs: number;
  avgMs: number;
  fails: number;
}

// ---------------------------------------------------------------------------
// Helpers (pure functions)
// ---------------------------------------------------------------------------

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function formatUsd(amount: number): string {
  const n = amount ?? 0;
  if (n < 0.001) return `$${n.toFixed(6)}`;
  if (n < 0.01)  return `$${n.toFixed(4)}`;
  if (n < 1)     return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

export function formatActivityBucket(bucket: string): string {
  switch (bucket) {
    case "code_changes":
      return "Code Changes";
    case "code_reading":
      return "Code Reading";
    case "search_discovery":
      return "Search & Discovery";
    case "command_execution":
      return "Command Execution";
    case "delegation":
      return "Sub-agents";
    case "reasoning":
      return "Reasoning";
    case "user_communication":
      return "User Messages";
    case "other_tools":
      return "Other Tools";
    case "bookkeeping":
      return "Bookkeeping";
    case "environment_setup":
      return "Setup";
    case "agent_reasoning":
      return "Reasoning";
    case "finalization":
      return "Finalization";
    case "post_completion":
      return "Post-completion";
    default:
      return bucket.replace(/_/g, " ");
  }
}

export function estimateCostWithoutCache(
  pricing: { input: number; output: number },
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens: number,
): number {
  return ((inputTokens + cacheReadTokens) * pricing.input + outputTokens * pricing.output) / 1_000_000;
}
