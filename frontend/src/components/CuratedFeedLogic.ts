/**
 * CuratedFeedLogic — pure types, constants, and functions for the CuratedFeed.
 *
 * No React imports — this module handles feed item construction, tool
 * classification, clustering, and file path utilities.
 */

import type { TranscriptEntry, ApprovalRequest } from "../store";
import {
  parseArgs,
  stripMcpPrefix,
} from "./ToolRenderers";
import type { FileText } from "lucide-react";

// ---------------------------------------------------------------------------
// Tool classification for clustering
// ---------------------------------------------------------------------------

export type ClusterKind = "read" | "write" | "create" | "execute" | "search" | "agent" | "web" | "other";

export const TOOL_KIND: Record<string, ClusterKind> = {
  // Read
  read_file: "read", list_dir: "read", view: "read", Read: "read", LS: "read",
  NotebookRead: "read", view_image: "read", get_errors: "read",
  // Search
  file_search: "search", grep_search: "search", semantic_search: "search",
  glob: "search", grep: "search", Glob: "search", Grep: "search",
  tool_search_tool_regex: "search", ToolSearch: "search",
  // Create
  create_file: "create", create: "create", Write: "create",
  create_or_update_file: "create",
  // Write
  replace_string_in_file: "write", multi_replace_string_in_file: "write",
  str_replace_based_edit_tool: "write", str_replace_editor: "write",
  edit: "write", Edit: "write", MultiEdit: "write",
  insert_edit_into_file: "write", write: "write", NotebookEdit: "write",
  apply_patch: "write", delete_file: "write",
  // Execute
  bash: "execute", run_in_terminal: "execute", get_terminal_output: "execute", Bash: "execute",
  // Agent
  runSubagent: "agent", search_subagent: "agent", skill: "agent",
  Task: "agent", task: "agent", Agent: "agent", read_agent: "agent",
  // Web
  fetch_webpage: "web", web_search: "web", WebFetch: "web", WebSearch: "web",
  ReadMcpResource: "web",
};

export function classifyTool(toolName?: string): ClusterKind {
  if (!toolName) return "other";
  const name = toolName.includes("/") ? toolName.split("/").pop()! : toolName;
  return TOOL_KIND[name] ?? "other";
}

// ---------------------------------------------------------------------------
// Cluster label helpers
// ---------------------------------------------------------------------------

export const KIND_LABELS: Record<ClusterKind, { singular: string; plural: string; icon: typeof FileText }> = {
  read:    { singular: "Read", plural: "Read", icon: null! },
  write:   { singular: "Edited", plural: "Edited", icon: null! },
  create:  { singular: "Created", plural: "Created", icon: null! },
  execute: { singular: "Ran", plural: "Ran", icon: null! },
  search:  { singular: "Searched", plural: "Searched", icon: null! },
  agent:   { singular: "Sub-agent", plural: "Sub-agents", icon: null! },
  web:     { singular: "Fetched", plural: "Fetched", icon: null! },
  other:   { singular: "Action", plural: "Actions", icon: null! },
};

export const KIND_ICON_COLORS: Record<ClusterKind, string> = {
  read:    "text-blue-400/70",
  write:   "text-amber-400/70",
  create:  "text-emerald-400/70",
  execute: "text-emerald-400/70",
  search:  "text-violet-400/70",
  agent:   "text-primary/70",
  web:     "text-cyan-400/70",
  other:   "text-muted-foreground/60",
};

export function clusterLabel(kind: ClusterKind, count: number): string {
  const info = KIND_LABELS[kind];
  if (kind === "read") return `Read ${count} file${count > 1 ? "s" : ""}`;
  if (kind === "write") return `Edited ${count} file${count > 1 ? "s" : ""}`;
  if (kind === "create") return `Created ${count} file${count > 1 ? "s" : ""}`;
  if (kind === "execute") return `Ran ${count} command${count > 1 ? "s" : ""}`;
  if (kind === "search") return `${count} search${count > 1 ? "es" : ""}`;
  if (kind === "agent") return `${count} sub-agent${count > 1 ? "s" : ""}`;
  if (kind === "web") return `Fetched ${count} page${count > 1 ? "s" : ""}`;
  return `${count} ${count > 1 ? info.plural.toLowerCase() : info.singular.toLowerCase()}`;
}

// ---------------------------------------------------------------------------
// Turn grouping types
// ---------------------------------------------------------------------------

export interface AgentTurn {
  key: string;
  reasoning: TranscriptEntry | null;
  toolCalls: TranscriptEntry[];
  message: TranscriptEntry | null;
  firstTimestamp: string;
  turnId: string | null;
}

export interface ActionCluster {
  kind: ClusterKind;
  label: string;
  entries: TranscriptEntry[];
}

export type FeedItem =
  | { type: "operator"; entry: TranscriptEntry }
  | { type: "turn"; turn: AgentTurn; clusters: ActionCluster[] }
  | { type: "condensed"; turn: AgentTurn; clusters: ActionCluster[] }
  | { type: "approval"; approval: ApprovalRequest }
  | { type: "divider"; entry: TranscriptEntry };

// ---------------------------------------------------------------------------
// File path utilities
// ---------------------------------------------------------------------------

export interface PhaseFile {
  key: string;
  fileName: string;
  relativePath: string;
  entries: TranscriptEntry[];
}

/** Extract a dedup key (file path or command) from a tool call entry. */
export function extractFileKey(entry: TranscriptEntry): string {
  const args = parseArgs(entry.toolArgs);
  const kind = classifyTool(entry.toolName);

  if (kind === "read" || kind === "write" || kind === "create") {
    const path = (args.filePath ?? args.file_path ?? args.path ?? "") as string;
    if (path) return path;
  }
  if (kind === "execute") {
    return (args.command as string) ?? entry.toolDisplay ?? `cmd-${entry.seq}`;
  }
  if (kind === "search") {
    return (args.query ?? args.pattern ?? "") as string || `search-${entry.seq}`;
  }
  // multi_replace: extract first file
  const name = stripMcpPrefix(entry.toolName ?? "");
  if (name === "multi_replace_string_in_file" || name === "MultiEdit") {
    const edits = (args.replacements ?? args.edits ?? []) as Array<Record<string, unknown>>;
    const firstPath = edits[0] && ((edits[0].filePath ?? edits[0].file_path ?? edits[0].path ?? "") as string);
    if (firstPath) return firstPath;
  }
  return entry.toolDisplay ?? `entry-${entry.seq}`;
}

/** Extract just the filename from a path. */
export function fileNameOnly(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1]! : path;
}

/** Path relative to worktree root (strips worktree prefix). */
export function relativeToWorktree(path: string): string {
  const MARKER = "/.codeplane-worktrees/";
  const idx = path.indexOf(MARKER);
  if (idx !== -1) {
    const afterMarker = path.slice(idx + MARKER.length);
    const slashIdx = afterMarker.indexOf("/");
    return slashIdx !== -1 ? afterMarker.slice(slashIdx + 1) : afterMarker;
  }
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length <= 3 ? path : parts.slice(-3).join("/");
}

/** True if the path is inside the job worktree (a repo file, not a temp/session artifact). */
export function isRepoFile(path: string): boolean {
  if (!path) return false;
  if (path.includes("/.codeplane-worktrees/")) return true;
  if (path.startsWith("/tmp/") || path.startsWith("/tmp\\")) return false;
  if (path.includes("/.copilot/")) return false;
  if (path.includes("/session-state/")) return false;
  if (path.includes("/.vscode")) return false;
  return true;
}

export function deduplicateByFile(entries: TranscriptEntry[]): PhaseFile[] {
  const map = new Map<string, PhaseFile>();
  for (const e of entries) {
    const key = extractFileKey(e);
    const existing = map.get(key);
    if (existing) {
      existing.entries.push(e);
    } else {
      const kind = classifyTool(e.toolName);
      let fileName: string;
      let relativePath: string;
      if (kind === "execute") {
        const args = parseArgs(e.toolArgs);
        const cmd = (args.command as string) ?? "";
        fileName = cmd.length > 40 ? cmd.slice(0, 40) + "…" : cmd;
        relativePath = cmd;
      } else if (kind === "search") {
        const args = parseArgs(e.toolArgs);
        const q = ((args.query ?? args.pattern ?? "") as string).slice(0, 30);
        fileName = `"${q}"`;
        relativePath = `"${q}"`;
      } else {
        fileName = fileNameOnly(key);
        relativePath = relativeToWorktree(key);
      }
      map.set(key, { key, fileName, relativePath, entries: [e] });
    }
  }
  return [...map.values()];
}

// ---------------------------------------------------------------------------
// Feed item building
// ---------------------------------------------------------------------------

export function buildFeedItems(
  entries: TranscriptEntry[],
  approvals: ApprovalRequest[],
): FeedItem[] {
  const items: FeedItem[] = [];
  const pendingApprovals = new Map(approvals.map((a) => [a.requestedAt, a]));

  let currentTurn: AgentTurn | null = null;

  function flushTurn() {
    if (!currentTurn) return;

    // Deduplicate tool_running/tool_call pairs
    const completedNames = new Map<string, number>();
    for (const e of currentTurn.toolCalls) {
      if (e.role === "tool_call" && e.toolName) {
        completedNames.set(e.toolName, (completedNames.get(e.toolName) ?? 0) + 1);
      }
    }
    const runningCounts = new Map<string, number>();
    currentTurn.toolCalls = currentTurn.toolCalls.filter((e) => {
      if (e.role !== "tool_running" || !e.toolName) return true;
      const limit = completedNames.get(e.toolName) ?? 0;
      if (limit <= 0) return true;
      const seen = (runningCounts.get(e.toolName) ?? 0) + 1;
      runningCounts.set(e.toolName, seen);
      if (seen <= limit) return false;
      return true;
    });

    // Filter out hidden tools
    const FRONTEND_HIDDEN = new Set([
      "report_intent", "manage_todo_list", "TodoWrite", "TodoRead",
      "Think", "Sql", "sql", "ListMcpResourceTemplates", "ListMcpResources",
    ]);
    currentTurn.toolCalls = currentTurn.toolCalls.filter((e) => {
      if (e.toolVisibility === "hidden") return false;
      const name = e.toolName?.includes("/") ? e.toolName.split("/").pop()! : e.toolName;
      if (name && FRONTEND_HIDDEN.has(name)) return false;
      return true;
    });

    const clusters = clusterToolCalls(currentTurn.toolCalls);

    const hasMessage = !!currentTurn.message?.content?.trim();
    if (hasMessage) {
      items.push({ type: "turn", turn: currentTurn, clusters });
    } else if (currentTurn.toolCalls.length > 0) {
      items.push({ type: "condensed", turn: currentTurn, clusters });
    }

    currentTurn = null;
  }

  for (const entry of entries) {
    for (const [ts, approval] of pendingApprovals) {
      if (ts <= entry.timestamp) {
        flushTurn();
        items.push({ type: "approval", approval });
        pendingApprovals.delete(ts);
      }
    }

    if (entry.role === "operator") {
      flushTurn();
      items.push({ type: "operator", entry });
      continue;
    }

    if (entry.role === "divider") {
      flushTurn();
      items.push({ type: "divider", entry });
      continue;
    }

    if (entry.role === "thinking" || entry.role === "reasoning") {
      if (currentTurn && entry.turnId && currentTurn.turnId && entry.turnId !== currentTurn.turnId) {
        flushTurn();
      }
      if (!currentTurn) {
        currentTurn = { key: `t-${entry.seq}`, reasoning: entry, toolCalls: [], message: null, firstTimestamp: entry.timestamp, turnId: entry.turnId ?? null };
      } else if (!currentTurn.reasoning) {
        currentTurn.reasoning = entry;
      }
      continue;
    }

    if (entry.role === "tool_call" || entry.role === "tool_running") {
      if (currentTurn && entry.turnId && currentTurn.turnId && entry.turnId !== currentTurn.turnId) {
        flushTurn();
      }
      if (!currentTurn) {
        currentTurn = { key: `t-${entry.seq}`, reasoning: null, toolCalls: [], message: null, firstTimestamp: entry.timestamp, turnId: entry.turnId ?? null };
      }
      currentTurn.toolCalls.push(entry);
      continue;
    }

    if (entry.role === "agent") {
      if (currentTurn && entry.turnId && currentTurn.turnId && entry.turnId !== currentTurn.turnId) {
        flushTurn();
      }
      if (!currentTurn) {
        currentTurn = { key: `t-${entry.seq}`, reasoning: null, toolCalls: [], message: null, firstTimestamp: entry.timestamp, turnId: entry.turnId ?? null };
      }
      currentTurn.message = entry;
      flushTurn();
      continue;
    }
  }

  flushTurn();

  for (const approval of pendingApprovals.values()) {
    items.push({ type: "approval", approval });
  }

  return items;
}

export function clusterToolCalls(calls: TranscriptEntry[]): ActionCluster[] {
  if (calls.length === 0) return [];

  const countForLabel = (kind: ClusterKind, entries: TranscriptEntry[]): number =>
    (kind === "read" || kind === "write" || kind === "create")
      ? new Set(entries.map(e => extractFileKey(e))).size
      : entries.length;

  const filtered = calls.filter((call) => {
    const kind = classifyTool(call.toolName);
    if (kind === "read" || kind === "write" || kind === "create") {
      const key = extractFileKey(call);
      if (!isRepoFile(key)) return false;
    }
    return true;
  });
  if (filtered.length === 0) return [];

  const clusters: ActionCluster[] = [];
  let currentKind: ClusterKind | null = null;
  let currentEntries: TranscriptEntry[] = [];

  for (const call of filtered) {
    const kind = classifyTool(call.toolName);
    if (kind === "other") {
      if (currentKind !== null && currentEntries.length > 0) {
        clusters.push({ kind: currentKind, label: clusterLabel(currentKind, countForLabel(currentKind, currentEntries)), entries: currentEntries });
        currentKind = null;
        currentEntries = [];
      }
      const display = call.toolDisplay ?? call.toolName ?? "Tool";
      clusters.push({ kind: "other", label: display, entries: [call] });
    } else if (kind === currentKind) {
      currentEntries.push(call);
    } else {
      if (currentKind !== null && currentEntries.length > 0) {
        clusters.push({ kind: currentKind, label: clusterLabel(currentKind, countForLabel(currentKind, currentEntries)), entries: currentEntries });
      }
      currentKind = kind;
      currentEntries = [call];
    }
  }
  if (currentKind !== null && currentEntries.length > 0) {
    clusters.push({ kind: currentKind, label: clusterLabel(currentKind, countForLabel(currentKind, currentEntries)), entries: currentEntries });
  }

  return clusters;
}

// ---------------------------------------------------------------------------
// Diff computation (pure function)
// ---------------------------------------------------------------------------

export type DiffLine = { type: "ctx" | "del" | "add"; text: string; oldNo?: number; newNo?: number };

export function computeLineDiff(oldStr: string, newStr: string, contextLines = 3): DiffLine[] {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");

  let prefixLen = 0;
  while (
    prefixLen < oldLines.length &&
    prefixLen < newLines.length &&
    oldLines[prefixLen] === newLines[prefixLen]
  ) {
    prefixLen++;
  }

  let suffixLen = 0;
  while (
    suffixLen < oldLines.length - prefixLen &&
    suffixLen < newLines.length - prefixLen &&
    oldLines[oldLines.length - 1 - suffixLen] === newLines[newLines.length - 1 - suffixLen]
  ) {
    suffixLen++;
  }

  const removedLines = oldLines.slice(prefixLen, oldLines.length - suffixLen);
  const addedLines = newLines.slice(prefixLen, newLines.length - suffixLen);

  const ctxBefore = oldLines.slice(Math.max(0, prefixLen - contextLines), prefixLen);
  const ctxAfter = oldLines.slice(
    oldLines.length - suffixLen,
    Math.min(oldLines.length, oldLines.length - suffixLen + contextLines),
  );

  const startLineOld = Math.max(0, prefixLen - contextLines) + 1;
  const startLineNew = Math.max(0, prefixLen - contextLines) + 1;

  const result: DiffLine[] = [];

  let oldNo = startLineOld;
  let newNo = startLineNew;

  if (prefixLen > contextLines) {
    result.push({ type: "ctx", text: "···" });
  }

  for (const line of ctxBefore) {
    result.push({ type: "ctx", text: line, oldNo, newNo });
    oldNo++;
    newNo++;
  }
  for (const line of removedLines) {
    result.push({ type: "del", text: line, oldNo });
    oldNo++;
  }
  for (const line of addedLines) {
    result.push({ type: "add", text: line, newNo });
    newNo++;
  }
  for (const line of ctxAfter) {
    result.push({ type: "ctx", text: line, oldNo, newNo });
    oldNo++;
    newNo++;
  }

  if (suffixLen > contextLines) {
    result.push({ type: "ctx", text: "···" });
  }

  return result;
}
