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
  activityPhase?: CostDriverBucket[];
  editEfficiency?: CostDriverBucket[];
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
    case "debugging":
      return "Debugging";
    case "refactoring":
      return "Refactoring";
    case "feature_dev":
      return "Feature Dev";
    case "testing":
      return "Testing";
    case "git_ops":
      return "Git Ops";
    case "build_deploy":
      return "Build / Deploy";
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

// ---------------------------------------------------------------------------
// Activity descriptions — explains what each cost category actually means
// ---------------------------------------------------------------------------

export const ACTIVITY_DESCRIPTIONS: Record<string, string> = {
  command_execution: "Turns where the agent ran shell commands (bash, terminal, sql)",
  code_reading: "Turns where the agent read files or checked git status/diffs",
  reasoning: "Turns of explicit thinking (Think tool) with no user-facing output",
  user_communication: "Turns where the agent composed a message to you (no tool calls)",
  code_changes: "Turns where the agent edited/created files or committed git changes",
  delegation: "Turns where the agent delegated to sub-agents",
  search_discovery: "Turns where the agent searched code or fetched URLs",
  other_tools: "Turns using unclassified or custom tools",
  bookkeeping: "Turns where the agent managed todos, memory, or intent tracking",
  debugging: "Turns where the agent fixed bugs, errors, or failing code",
  refactoring: "Turns where the agent restructured, renamed, or simplified code",
  feature_dev: "Turns where the agent built new features or scaffolded components",
  testing: "Turns where the agent ran or wrote tests",
  git_ops: "Turns where the agent ran git commands (push, commit, merge, etc.)",
  build_deploy: "Turns where the agent ran build, install, or deploy commands",
};

// ---------------------------------------------------------------------------
// Tool → activity category mapping (mirrors backend tool_classifier.py)
// ---------------------------------------------------------------------------

const TOOL_TO_CATEGORY: Record<string, string> = {
  read_file: "file_read", view: "file_read", cat: "file_read", Read: "file_read",
  readFile: "file_read", open_file: "file_read", view_image: "file_read",
  edit_file: "file_write", edit: "file_write", create_file: "file_write",
  write_file: "file_write", write: "file_write", Write: "file_write",
  Edit: "file_write", MultiEdit: "file_write", editFile: "file_write",
  replace_string_in_file: "file_write", multi_replace_string_in_file: "file_write",
  str_replace_based_edit_tool: "file_write", str_replace_editor: "file_write",
  insert_edit_into_file: "file_write", apply_patch: "file_write",
  delete_file: "file_write", create_directory: "file_write",
  grep: "file_search", grep_search: "file_search", Grep: "file_search",
  glob: "file_search", Glob: "file_search", find: "file_search",
  rg: "file_search", search: "file_search", semantic_search: "file_search",
  list_dir: "file_search", listDir: "file_search", LS: "file_search",
  file_search: "file_search", vscode_listCodeUsages: "file_search",
  bash: "shell", Bash: "shell", terminal: "shell", exec: "shell",
  run_in_terminal: "shell", get_terminal_output: "shell",
  read_bash: "shell", write_bash: "shell", stop_bash: "shell", sql: "shell",
  git_diff: "git_read", git_status: "git_read", git_log: "git_read",
  get_changed_files: "git_read",
  git_commit: "git_write", git_push: "git_write", git_add: "git_write",
  git_checkout: "git_write", git_merge: "git_write",
  fetch_url: "browser", web_search: "browser", web_fetch: "browser",
  WebFetch: "browser", WebSearch: "browser", fetch_webpage: "browser",
  task: "agent", subagent: "agent", Agent: "agent", runSubagent: "agent",
  Task: "agent",
  Think: "thinking", Computer: "thinking",
  report_intent: "bookkeeping", store_memory: "bookkeeping",
  manage_todo_list: "bookkeeping", memory: "bookkeeping",
};

const CATEGORY_TO_ACTIVITY: Record<string, string> = {
  file_write: "code_changes",
  git_write: "code_changes",
  git_read: "code_reading",
  file_read: "code_reading",
  file_search: "search_discovery",
  browser: "search_discovery",
  shell: "command_execution",
  agent: "delegation",
  thinking: "reasoning",
  bookkeeping: "bookkeeping",
  other: "other_tools",
};

/** Classify a tool name into its activity bucket. */
export function classifyToolToActivity(toolName: string): string {
  const cat = TOOL_TO_CATEGORY[toolName]
    ?? (toolName.includes("/") ? TOOL_TO_CATEGORY[toolName.split("/").pop()!] : undefined)
    ?? "other";
  return CATEGORY_TO_ACTIVITY[cat] ?? "other_tools";
}

/** Representative tool examples for each activity, shown when no real data. */
export const ACTIVITY_TOOL_EXAMPLES: Record<string, string[]> = {
  command_execution: ["bash", "run_in_terminal", "sql"],
  code_reading: ["read_file", "view", "git_diff", "git_status"],
  reasoning: ["Think"],
  user_communication: [],
  code_changes: ["edit_file", "write_file", "replace_string_in_file", "git_commit"],
  delegation: ["runSubagent", "Task"],
  search_discovery: ["grep_search", "semantic_search", "file_search", "web_search"],
  other_tools: [],
  bookkeeping: ["manage_todo_list", "memory", "report_intent"],
  debugging: ["edit_file", "bash (fix loops)"],
  refactoring: ["edit_file", "replace_string_in_file"],
  feature_dev: ["create_file", "edit_file"],
  testing: ["bash (pytest/vitest)", "edit_file"],
  git_ops: ["bash (git push/commit/merge)"],
  build_deploy: ["bash (npm build, pip install)"],
};

const _PHASE_COLORS: Record<string, string> = {
  environment_setup: "bg-cyan-500",
  agent_reasoning: "bg-blue-500",
  verification: "bg-amber-500",
  finalization: "bg-purple-500",
  post_completion: "bg-slate-400",
};

const _PHASE_SHORT_LABELS: Record<string, string> = {
  environment_setup: "Setup",
  agent_reasoning: "Reasoning",
  verification: "Verify",
  finalization: "Final",
  post_completion: "Post",
};

export function phaseColor(phase: string): string {
  return _PHASE_COLORS[phase] ?? "bg-gray-400";
}

export function phaseShortLabel(phase: string): string {
  return _PHASE_SHORT_LABELS[phase] ?? phase.replace(/_/g, " ");
}

export function estimateCostWithoutCache(
  pricing: { input: number; output: number },
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens: number,
): number {
  return ((inputTokens + cacheReadTokens) * pricing.input + outputTokens * pricing.output) / 1_000_000;
}
