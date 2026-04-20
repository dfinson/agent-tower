/* eslint-disable react-refresh/only-export-components -- exports useSearchHighlight alongside components */
/**
 * CuratedFeed — curated, structured activity view with progressive disclosure.
 *
 * Design principles:
 * - Whitelist rendering: only high-signal info is visible by default
 * - Action clustering: consecutive similar tools → single chip ("Read 5 files")
 * - Progressive disclosure: expand clusters on click for full detail
 * - Agent messages always shown in full (they ARE the high signal)
 * - Reasoning shown as subtle secondary text
 * - Minimal visual weight, muted colors
 */

import { useRef, useEffect, useState, useCallback, useMemo, memo, createContext, useContext } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useNavigate } from "react-router-dom";
import {
  Send, Bot, User, ChevronDown, ChevronUp, ChevronRight, Brain,
  ShieldQuestion, CheckCircle2, XCircle as XCircleIcon,
  ArrowDown, Search, PauseCircle, X, GitBranch, GitFork,
  FileText, Pencil, FilePlus, Terminal, Globe, Cpu,
  Clock, Milestone,
} from "lucide-react";
import { toast } from "sonner";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useStore, selectJobTranscript, selectApprovals, selectStreamingToolOutput } from "../store";
import { useShallow } from "zustand/react/shallow";
import type { TranscriptEntry, ApprovalRequest } from "../store";
import { sendOperatorMessage, continueJob, resumeJob, pauseJob, resolveApproval, ApiError } from "../api/client";
import { AgentMarkdown } from "./AgentMarkdown";
import { SdkIcon } from "./SdkBadge";
import { MicButton } from "./VoiceButton";
import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";
import { Tooltip } from "./ui/tooltip";
import Ansi from "ansi-to-react";
import {
  formatDuration,
  trimWorktreePaths,
  parseArgs,
  stripMcpPrefix,
  TruncatedPayload,
} from "./ToolRenderers";
import { SyntaxBlock } from "./SyntaxBlock";
import { detectLanguage } from "../lib/detectLanguage";

// ---------------------------------------------------------------------------
// Search highlight context — provides the active search query to children
// ---------------------------------------------------------------------------
const SearchHighlightCtx = createContext("");
export const useSearchHighlight = () => useContext(SearchHighlightCtx);

/** Wrapper that injects search highlight from context into AgentMarkdown. */
function HighlightedMarkdown({ content }: { content: string }) {
  const hl = useSearchHighlight();
  return <AgentMarkdown content={content} highlight={hl || undefined} />;
}

// ---------------------------------------------------------------------------
// Tool classification for clustering
// ---------------------------------------------------------------------------

type ClusterKind = "read" | "write" | "create" | "execute" | "search" | "agent" | "web" | "other";

const TOOL_KIND: Record<string, ClusterKind> = {
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

function classifyTool(toolName?: string): ClusterKind {
  if (!toolName) return "other";
  const name = toolName.includes("/") ? toolName.split("/").pop()! : toolName;
  return TOOL_KIND[name] ?? "other";
}

// ---------------------------------------------------------------------------
// Cluster label helpers
// ---------------------------------------------------------------------------

const KIND_LABELS: Record<ClusterKind, { singular: string; plural: string; icon: typeof FileText }> = {
  read:    { singular: "Read", plural: "Read", icon: FileText },
  write:   { singular: "Edited", plural: "Edited", icon: Pencil },
  create:  { singular: "Created", plural: "Created", icon: FilePlus },
  execute: { singular: "Ran", plural: "Ran", icon: Terminal },
  search:  { singular: "Searched", plural: "Searched", icon: Search },
  agent:   { singular: "Sub-agent", plural: "Sub-agents", icon: Cpu },
  web:     { singular: "Fetched", plural: "Fetched", icon: Globe },
  other:   { singular: "Action", plural: "Actions", icon: Bot },
};

// Phase 3: Semantic icon colors — warm up tool cluster icons
const KIND_ICON_COLORS: Record<ClusterKind, string> = {
  read:    "text-blue-400/50",
  write:   "text-amber-400/50",
  create:  "text-emerald-400/50",
  execute: "text-emerald-400/50",
  search:  "text-violet-400/50",
  agent:   "text-primary/50",
  web:     "text-cyan-400/50",
  other:   "text-muted-foreground/50",
};

function clusterLabel(kind: ClusterKind, count: number): string {
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
// Turn grouping (reasoning → tool_call* → agent message)
// ---------------------------------------------------------------------------

interface AgentTurn {
  key: string;
  reasoning: TranscriptEntry | null;
  toolCalls: TranscriptEntry[];
  message: TranscriptEntry | null;
  firstTimestamp: string;
  turnId: string | null;
}

interface ActionCluster {
  kind: ClusterKind;
  label: string;
  entries: TranscriptEntry[];
}

type FeedItem =
  | { type: "operator"; entry: TranscriptEntry }
  | { type: "turn"; turn: AgentTurn; clusters: ActionCluster[] }
  | { type: "condensed"; turn: AgentTurn; clusters: ActionCluster[] }
  | { type: "approval"; approval: ApprovalRequest }
  | { type: "divider"; entry: TranscriptEntry };

function buildFeedItems(
  entries: TranscriptEntry[],
  approvals: ApprovalRequest[],
): FeedItem[] {
  const items: FeedItem[] = [];
  const pendingApprovals = new Map(approvals.map((a) => [a.requestedAt, a]));

  // Group entries into turns
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
      if (limit <= 0) return true; // no completion yet, keep the running entry
      const seen = (runningCounts.get(e.toolName) ?? 0) + 1;
      runningCounts.set(e.toolName, seen);
      if (seen <= limit) return false; // has a completion, drop the running entry
      return true;
    });

    // Filter out hidden tools (backend visibility + frontend fallback for legacy data)
    const FRONTEND_HIDDEN = new Set(["report_intent", "manage_todo_list", "TodoWrite", "TodoRead", "Think", "Sql", "sql"]);
    currentTurn.toolCalls = currentTurn.toolCalls.filter((e) => {
      if (e.toolVisibility === "hidden") return false;
      const name = e.toolName?.includes("/") ? e.toolName.split("/").pop()! : e.toolName;
      if (name && FRONTEND_HIDDEN.has(name)) return false;
      return true;
    });

    // Cluster the tool calls
    const clusters = clusterToolCalls(currentTurn.toolCalls);

    // Decide: condensed or full?
    const hasMessage = !!currentTurn.message?.content?.trim();
    if (hasMessage) {
      items.push({ type: "turn", turn: currentTurn, clusters });
    } else if (currentTurn.toolCalls.length > 0) {
      items.push({ type: "condensed", turn: currentTurn, clusters });
    }
    // Turns with no message and no tools are dropped (pure noise)

    currentTurn = null;
  }

  for (const entry of entries) {
    // Inject approval cards at the right timestamp
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
      // Flush on turnId boundary (mirrors backend step_tracker turn_change detection)
      if (currentTurn && entry.turnId && currentTurn.turnId && entry.turnId !== currentTurn.turnId) {
        flushTurn();
      }
      // Start a new turn if needed, or attach to current
      if (!currentTurn) {
        currentTurn = { key: `t-${entry.seq}`, reasoning: entry, toolCalls: [], message: null, firstTimestamp: entry.timestamp, turnId: entry.turnId ?? null };
      } else if (!currentTurn.reasoning) {
        currentTurn.reasoning = entry;
      }
      continue;
    }

    if (entry.role === "tool_call" || entry.role === "tool_running") {
      // Flush on turnId boundary
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
      // Flush on turnId boundary (before starting new turn for this message)
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

  // Flush any trailing turn
  flushTurn();

  // Remaining approvals
  for (const approval of pendingApprovals.values()) {
    items.push({ type: "approval", approval });
  }

  return items;
}

function clusterToolCalls(calls: TranscriptEntry[]): ActionCluster[] {
  if (calls.length === 0) return [];

  // For file-based kinds, count unique files rather than total operations
  const countForLabel = (kind: ClusterKind, entries: TranscriptEntry[]): number =>
    (kind === "read" || kind === "write" || kind === "create")
      ? new Set(entries.map(e => extractFileKey(e))).size
      : entries.length;

  // Filter out file operations on artifact/temp paths (not in the repo worktree)
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
    // "other" tools never cluster — each gets its own chip with its toolDisplay label
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
// Phase box — flat container with per-file chips, collapses to summary
// ---------------------------------------------------------------------------

/** Extract a dedup key (file path or command) from a tool call entry. */
function extractFileKey(entry: TranscriptEntry): string {
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

interface PhaseFile {
  key: string;
  fileName: string;       // just the filename (shown on chip)
  relativePath: string;   // path relative to worktree root (shown on hover + expand)
  entries: TranscriptEntry[];
}

/** Extract just the filename from a path. */
function fileNameOnly(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1]! : path;
}

/** Path relative to worktree root (strips worktree prefix). */
function relativeToWorktree(path: string): string {
  const MARKER = "/.codeplane-worktrees/";
  const idx = path.indexOf(MARKER);
  if (idx !== -1) {
    // Skip the worktree name segment: …/worktree-name/rest
    const afterMarker = path.slice(idx + MARKER.length);
    const slashIdx = afterMarker.indexOf("/");
    return slashIdx !== -1 ? afterMarker.slice(slashIdx + 1) : afterMarker;
  }
  // Fallback: last 3 segments
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length <= 3 ? path : parts.slice(-3).join("/");
}

/** True if the path is inside the job worktree (a repo file, not a temp/session artifact). */
function isRepoFile(path: string): boolean {
  if (!path) return false;
  if (path.includes("/.codeplane-worktrees/")) return true;
  // Exclude known artifact/temp locations
  if (path.startsWith("/tmp/") || path.startsWith("/tmp\\")) return false;
  if (path.includes("/.copilot/")) return false;
  if (path.includes("/session-state/")) return false;
  if (path.includes("/.vscode")) return false;
  return true;
}

function deduplicateByFile(entries: TranscriptEntry[]): PhaseFile[] {
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
        const cmd = trimWorktreePaths((args.command as string) ?? "");
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

function PhaseBox({
  cluster,
  defaultExpanded,
  onViewStepChanges,
}: {
  cluster: ActionCluster;
  defaultExpanded?: boolean;
  onViewStepChanges?: (filePaths: string[], label: string, scrollToSeq?: number, turnId?: string) => void;
}) {
  const searchQuery = useSearchHighlight();
  // Auto-expand when search matches an entry inside this cluster
  const hasSearchMatch = !!searchQuery && cluster.entries.some((e) =>
    e.toolDisplay?.toLowerCase().includes(searchQuery)
    || e.toolName?.toLowerCase().includes(searchQuery)
  );
  const [manualExpanded, setManualExpanded] = useState(defaultExpanded ?? false);
  // Expand if either manually expanded or search made a match
  const expanded = manualExpanded || hasSearchMatch;
  const setExpanded = setManualExpanded;
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const Icon = KIND_LABELS[cluster.kind].icon;
  const files = useMemo(() => deduplicateByFile(cluster.entries), [cluster.entries]);
  const totalDuration = cluster.entries.reduce((sum, e) => sum + (e.toolDurationMs ?? 0), 0);
  const hasEdits = cluster.kind === "write" || cluster.kind === "create";

  // First entry seq — used as scroll anchor from the diff tab back to this spot
  const firstSeq = cluster.entries[0]?.seq;
  // Turn ID — used to fetch step-specific diff from the API
  const turnId = cluster.entries[0]?.turnId;

  const handleViewChanges = useCallback(() => {
    if (!onViewStepChanges) return;
    const paths = files.map((f) => f.relativePath);
    // Build a descriptive label: "Edited models.py, views.py" or "Created INDEX.md +2 more"
    const verb = KIND_LABELS[cluster.kind].singular;
    const names = files.map((f) => f.fileName);
    const shown = names.slice(0, 2).join(", ");
    const rest = names.length > 2 ? ` +${names.length - 2} more` : "";
    onViewStepChanges(paths, `${verb} ${shown}${rest}`, firstSeq, turnId ?? undefined);
  }, [onViewStepChanges, files, cluster.kind, firstSeq, turnId]);

  // Collapsed: summary row
  if (!expanded) {
    return (
      <div className="flex items-center gap-1">
        <button
          onClick={() => setExpanded(true)}
          className={cn(
            "flex items-center gap-2 py-1.5 px-2.5 rounded-md flex-1 text-left",
            "text-xs text-muted-foreground hover:text-foreground hover:bg-accent/30 transition-colors",
            "border border-transparent hover:border-border/40",
          )}
        >
          <Icon size={12} className={cn("shrink-0", KIND_ICON_COLORS[cluster.kind])} />
          <span className="font-medium">{cluster.label}</span>
          {/* Phase 3: Show AI-generated tool group summary in collapsed view */}
          {cluster.entries[0]?.toolGroupSummary && (
            <span className="text-[11px] text-muted-foreground/40 italic truncate ml-1 flex-1 min-w-0">
              {cluster.entries[0].toolGroupSummary}
            </span>
          )}
          {totalDuration > 0 && (
            <span className="text-[10px] opacity-30 ml-auto shrink-0">{formatDuration(totalDuration)}</span>
          )}
          <ChevronRight size={11} className="opacity-30 shrink-0" />
        </button>
        {hasEdits && onViewStepChanges && (
          <button
            onClick={handleViewChanges}
            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-primary/70 hover:text-primary hover:bg-primary/10 transition-colors shrink-0"
            title="View changes in diff viewer"
          >
            <GitBranch size={10} />
            <span>View Changes</span>
          </button>
        )}
      </div>
    );
  }

  // Expanded: phase box with file chips
  const selectedFile = files.find((f) => f.key === selectedKey);

  return (
    <div className="rounded-md border border-border/40 bg-muted/5 overflow-hidden">
      {/* Phase header */}
      <div className="flex items-center gap-1 pr-1">
        <button
          onClick={() => setExpanded(false)}
          className="flex items-center gap-2 px-3 py-1.5 flex-1 text-left text-xs text-muted-foreground hover:text-foreground hover:bg-accent/20 transition-colors"
        >
          <Icon size={12} className={cn("shrink-0", KIND_ICON_COLORS[cluster.kind])} />
          <span className="font-medium">{cluster.label}</span>
          {totalDuration > 0 && (
            <span className="text-[10px] opacity-30 ml-auto shrink-0">{formatDuration(totalDuration)}</span>
          )}
          <ChevronDown size={11} className="opacity-30 shrink-0" />
        </button>
        {hasEdits && onViewStepChanges && (
          <button
            onClick={handleViewChanges}
            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-primary/70 hover:text-primary hover:bg-primary/10 transition-colors shrink-0"
            title="View changes in diff viewer"
          >
            <GitBranch size={10} />
            <span>View Changes</span>
          </button>
        )}
      </div>

      {/* File chips */}
      <div className="flex flex-wrap gap-1.5 px-3 py-2 border-t border-border/20">
        {files.map((f) => (
          <FileChip
            key={f.key}
            file={f}
            selected={selectedKey === f.key}
            onClick={() => setSelectedKey(selectedKey === f.key ? null : f.key)}
          />
        ))}
      </div>

      {/* Inline preview — directly below chips, left-aligned */}
      {selectedFile && (
        <div className="border-t border-border/20">
          <InlinePreview file={selectedFile} kind={cluster.kind} />
        </div>
      )}
    </div>
  );
}

function SubAgentBubble({
  cluster,
  sdk,
}: {
  cluster: ActionCluster;
  sdk?: string;
}) {
  const [expanded, setExpanded] = useState(false);

  // Find the best entry: prefer tool_call (completed) over tool_running
  const completedEntry = cluster.entries.find((e) => e.role === "tool_call");
  const runningEntry = cluster.entries.find((e) => e.role === "tool_running");
  const entry = completedEntry ?? runningEntry ?? cluster.entries[cluster.entries.length - 1]!;

  const args = parseArgs(entry.toolArgs);
  const description = (args.description as string) || entry.toolDisplay?.replace(/^Task:\s*/i, "") || "Sub-agent task";
  const isRunning = !completedEntry && !!runningEntry;
  const result = completedEntry?.toolResult ?? entry.toolResult;
  const totalDuration = cluster.entries.reduce((sum, e) => sum + (e.toolDurationMs ?? 0), 0);
  const hasResult = !!result?.trim();

  return (
    <div className="rounded-md border border-border/30 bg-card/50 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => hasResult && setExpanded(!expanded)}
        className={cn(
          "flex items-center gap-2.5 px-3 py-2 w-full text-left transition-colors",
          hasResult && "hover:bg-accent/20 cursor-pointer",
          !hasResult && "cursor-default",
        )}
      >
        <GitFork size={12} className={cn("shrink-0", isRunning ? "text-primary" : "text-muted-foreground/40")} />
        <span className={cn(
          "text-xs flex-1 min-w-0",
          isRunning ? "text-foreground/80 font-medium" : "text-muted-foreground",
        )}>
          {description}
          {isRunning && (
            <span className="inline-block w-1 h-3 bg-primary/60 animate-pulse ml-1.5 align-text-bottom rounded-sm" />
          )}
        </span>
        {totalDuration > 0 && !isRunning && (
          <span className="text-[10px] text-muted-foreground/30 shrink-0">{formatDuration(totalDuration)}</span>
        )}
        {hasResult && (
          expanded
            ? <ChevronDown size={11} className="opacity-30 shrink-0" />
            : <ChevronRight size={11} className="opacity-30 shrink-0" />
        )}
      </button>

      {/* Expanded result */}
      {expanded && hasResult && (
        <div className="border-t border-border/20 px-3 py-2">
          <div className="flex gap-2.5">
            <div className="shrink-0 w-5 h-5 rounded-full bg-muted/30 flex items-center justify-center mt-0.5">
              <SdkIcon sdk={sdk} size={12} fallback={<Bot size={11} className="text-muted-foreground/50" />} />
            </div>
            <div className="flex-1 min-w-0 text-xs text-foreground/80 leading-relaxed max-h-80 overflow-y-auto">
              <HighlightedMarkdown content={trimWorktreePaths(result!)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function FileChip({
  file,
  selected,
  onClick,
}: {
  file: PhaseFile;
  selected: boolean;
  onClick: () => void;
}) {
  const failed = file.entries.some((e) => e.toolSuccess === false);
  const isRunning = file.entries.some((e) => e.role === "tool_running");
  const editCount = file.entries.length > 1 ? file.entries.length : undefined;

  return (
    <button
      onClick={onClick}
      title={file.relativePath}
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono",
        "transition-colors cursor-pointer select-none",
        selected
          ? "bg-primary/15 text-primary border border-primary/30"
          : "bg-muted/30 text-muted-foreground hover:bg-accent/40 hover:text-foreground border border-transparent",
        failed && "text-red-400",
        isRunning && "animate-pulse",
      )}
    >
      <span className="truncate max-w-[140px] sm:max-w-[200px]">{file.fileName}</span>
      {editCount && <span className="text-[9px] opacity-50">×{editCount}</span>}
    </button>
  );
}

function InlinePreview({ file, kind }: { file: PhaseFile; kind: ClusterKind }) {
  return (
    <div>
      {/* Path header — relative to worktree root */}
      {kind !== "execute" && kind !== "search" && (
        <div className="px-3 py-1 text-[11px] font-mono text-muted-foreground/60 border-b border-border/10">
          {file.relativePath}
        </div>
      )}
      <InlinePreviewContent entries={file.entries} kind={kind} filePath={file.relativePath} />
    </div>
  );
}

function InlinePreviewContent({ entries, kind, filePath }: { entries: TranscriptEntry[]; kind: ClusterKind; filePath?: string }) {
  switch (kind) {
    case "execute":
      return <CommandPreview entries={entries} />;
    case "write":
      return <EditPreview entries={entries} filePath={filePath} />;
    case "read":
      return <ReadPreview entries={entries} filePath={filePath} />;
    case "create":
      return <CreatePreview entries={entries} filePath={filePath} />;
    case "search":
      return <SearchPreview entries={entries} />;
    default:
      return <GenericPreview entries={entries} />;
  }
}

function CommandPreview({ entries }: { entries: TranscriptEntry[] }) {
  const entry = entries[entries.length - 1]!;
  const args = parseArgs(entry.toolArgs);
  const command = trimWorktreePaths((args.command as string) ?? "");
  const failed = entry.toolSuccess === false;
  const isRunning = entry.role === "tool_running";
  const jobs = useStore((s) => s.jobs);
  const createTerminalSession = useStore((s) => s.createTerminalSession);
  const job = jobs[entry.jobId];
  const canOpenTerminal = !!job?.worktreePath;
  const streamingOutput = useStore(useShallow(selectStreamingToolOutput(entry.jobId)));
  const outputRef = useRef<HTMLPreElement>(null);

  // Find streaming output for this tool call (match by any available key)
  const liveOutput = useMemo(() => {
    if (!isRunning || !streamingOutput) return "";
    // Values are keyed by toolCallId — just return the first non-empty match
    const values = Object.values(streamingOutput);
    return values.length > 0 ? values[values.length - 1] : "";
  }, [isRunning, streamingOutput]);

  // Auto-scroll streaming output to bottom
  useEffect(() => {
    if (outputRef.current && liveOutput) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [liveOutput]);

  const handleOpenTerminal = useCallback(() => {
    if (!job?.worktreePath) return;
    createTerminalSession({ cwd: job.worktreePath, jobId: entry.jobId, label: job.branch ?? job.repo?.split("/").pop() ?? "Terminal" });
  }, [job, entry.jobId, createTerminalSession]);

  return (
    <div className="font-mono text-[13px] sm:text-xs">
      <div className={cn("px-3 py-1.5 flex items-start gap-2", failed ? "bg-red-950/20" : "bg-zinc-950/30")}>
        <div className="flex-1 min-w-0">
          <span className="text-muted-foreground">$ </span>
          <span className="text-foreground/90">{command}</span>
          {isRunning && !liveOutput && (
            <span className="ml-2 inline-block w-1.5 h-3 bg-primary/70 animate-pulse rounded-sm align-middle" />
          )}
        </div>
        {isRunning && canOpenTerminal && (
          <Tooltip content="Open terminal in worktree">
            <button
              onClick={handleOpenTerminal}
              className="shrink-0 p-1.5 sm:p-1 rounded text-foreground/60 hover:text-primary hover:bg-primary/20 transition-colors min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 flex items-center justify-center"
              aria-label="Open terminal"
            >
              <Terminal size={15} className="sm:w-3 sm:h-3" />
            </button>
          </Tooltip>
        )}
      </div>
      {/* Live streaming output while command is running */}
      {isRunning && liveOutput && (
        <pre
          ref={outputRef}
          className="px-3 py-1.5 text-[12px] sm:text-[11px] text-muted-foreground/80 whitespace-pre-wrap break-words max-h-48 overflow-y-auto border-l-2 border-primary/30 bg-zinc-950/20"
        >
          <Ansi>{liveOutput}</Ansi>
          <span className="inline-block w-1.5 h-3 bg-primary/70 animate-pulse rounded-sm align-middle ml-0.5" />
        </pre>
      )}
      {entry.toolResult && (
        <div className="px-3 py-1.5">
          <SyntaxBlock content={trimWorktreePaths(entry.toolResult)} language="bash" maxLength={600} />
        </div>
      )}
      {failed && entry.toolIssue && (
        <div className="px-3 py-1 text-red-400 text-[11px]">{entry.toolIssue}</div>
      )}
    </div>
  );
}

/** Compute a simple line-level diff between old and new text. */
function computeLineDiff(oldStr: string, newStr: string, contextLines = 3) {
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");

  // Find common prefix lines
  let prefixLen = 0;
  while (
    prefixLen < oldLines.length &&
    prefixLen < newLines.length &&
    oldLines[prefixLen] === newLines[prefixLen]
  ) {
    prefixLen++;
  }

  // Find common suffix lines (not overlapping prefix)
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

  // Context: up to N lines before/after the changed region
  const ctxBefore = oldLines.slice(Math.max(0, prefixLen - contextLines), prefixLen);
  const ctxAfter = oldLines.slice(
    oldLines.length - suffixLen,
    Math.min(oldLines.length, oldLines.length - suffixLen + contextLines),
  );

  // Line numbers (1-based): the context-before starts at this line in old file
  const startLineOld = Math.max(0, prefixLen - contextLines) + 1;
  const startLineNew = Math.max(0, prefixLen - contextLines) + 1;

  type DiffLine = { type: "ctx" | "del" | "add"; text: string; oldNo?: number; newNo?: number };
  const result: DiffLine[] = [];

  let oldNo = startLineOld;
  let newNo = startLineNew;

  // Collapse indicator if we skipped prefix lines
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

  // Collapse indicator if we skipped suffix lines
  if (suffixLen > contextLines) {
    result.push({ type: "ctx", text: "···" });
  }

  return result;
}

const MAX_DIFF_LINES = 30;

function DiffLines({ oldStr, newStr }: { oldStr: string; newStr: string }) {
  const lines = useMemo(() => computeLineDiff(oldStr, newStr), [oldStr, newStr]);
  const capped = lines.length > MAX_DIFF_LINES;
  const visible = capped ? lines.slice(0, MAX_DIFF_LINES) : lines;
  const gutterWidth = Math.max(
    ...lines.map((l) => Math.max(l.oldNo ?? 0, l.newNo ?? 0)),
  ).toString().length;

  return (
    <div className="font-mono text-[11px] leading-relaxed overflow-x-auto">
      {visible.map((line, i) => {
        const isCollapse = line.text === "···";
        if (isCollapse) {
          return (
            <div key={i} className="text-muted-foreground/40 select-none px-1">
              {"  ".repeat(gutterWidth)}  ···
            </div>
          );
        }
        const oldGutter = line.oldNo != null ? String(line.oldNo).padStart(gutterWidth) : " ".repeat(gutterWidth);
        const newGutter = line.newNo != null ? String(line.newNo).padStart(gutterWidth) : " ".repeat(gutterWidth);
        const prefix = line.type === "del" ? "-" : line.type === "add" ? "+" : " ";
        return (
          <div
            key={i}
            className={cn(
              "px-1 whitespace-pre",
              line.type === "del" && "bg-red-500/10 text-red-400/80",
              line.type === "add" && "bg-green-500/10 text-green-400/80",
              line.type === "ctx" && "text-muted-foreground/60",
            )}
          >
            <span className="text-muted-foreground/30 select-none">{oldGutter} {newGutter} </span>
            {prefix} {line.text}
          </div>
        );
      })}
      {capped && (
        <div className="text-muted-foreground/40 text-[10px] px-1 py-0.5">
          +{lines.length - MAX_DIFF_LINES} more lines
        </div>
      )}
    </div>
  );
}

function EditPreview({ entries }: { entries: TranscriptEntry[]; filePath?: string }) {
  return (
    <div className="text-[13px] sm:text-xs space-y-0">
      {entries.map((entry, i) => {
        const args = parseArgs(entry.toolArgs);
        const name = stripMcpPrefix(entry.toolName ?? "");
        const failed = entry.toolSuccess === false;

        // multi_replace / MultiEdit
        if (name === "multi_replace_string_in_file" || name === "MultiEdit") {
          const edits = (args.replacements ?? args.edits ?? []) as Array<Record<string, unknown>>;
          return (
            <div key={i} className="px-3 py-1.5 space-y-1.5">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Pencil size={10} className="text-amber-400 shrink-0" />
                <span>{edits.length} edits {failed ? "→ failed" : "→ applied"}</span>
              </div>
              {edits.slice(0, 6).map((e, j) => {
                const oldStr = (e.old_string ?? e.old_str ?? e.oldString) as string | undefined;
                const newStr = (e.new_string ?? e.new_str ?? e.newString) as string | undefined;
                return oldStr && newStr ? (
                  <div key={j} className={cn(j > 0 && "border-t border-border/10 pt-1.5")}>
                    <DiffLines oldStr={oldStr} newStr={newStr} />
                  </div>
                ) : null;
              })}
              {edits.length > 6 && (
                <div className="text-muted-foreground/50 text-[10px]">+{edits.length - 6} more</div>
              )}
            </div>
          );
        }

        // Single edit
        const oldStr = (args.old_str ?? args.old_string ?? args.oldString) as string | undefined;
        const newStr = (args.new_str ?? args.new_string ?? args.newString) as string | undefined;
        return (
          <div key={i} className={cn("px-3 py-1.5", i > 0 && "border-t border-border/10")}>
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Pencil size={10} className="text-amber-400 shrink-0" />
              <span>{failed ? "Failed" : "Applied"}</span>
              {entry.toolDurationMs != null && (
                <span className="text-[10px] opacity-40">{formatDuration(entry.toolDurationMs)}</span>
              )}
            </div>
            {typeof oldStr === "string" && typeof newStr === "string" && (
              <DiffLines oldStr={oldStr} newStr={newStr} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function ReadPreview({ entries, filePath }: { entries: TranscriptEntry[]; filePath?: string }) {
  // Show the content of the last read (most complete)
  const entry = entries[entries.length - 1]!;
  const args = parseArgs(entry.toolArgs);
  const startLine = (args.startLine ?? args.start_line) as number | undefined;
  const endLine = (args.endLine ?? args.end_line) as number | undefined;
  const range = startLine && endLine ? `lines ${startLine}–${endLine}` : null;
  const lang = detectLanguage(filePath);

  return (
    <div className="text-[13px] sm:text-xs">
      {range && (
        <div className="px-3 py-1 text-muted-foreground/60">{range}</div>
      )}
      {entry.toolResult && (
        <SyntaxBlock
          content={trimWorktreePaths(entry.toolResult)}
          language={lang}
          maxLength={800}
          showLineNumbers={!!startLine}
          startLine={startLine ?? 1}
        />
      )}
    </div>
  );
}

function CreatePreview({ entries, filePath }: { entries: TranscriptEntry[]; filePath?: string }) {
  const entry = entries[0]!;
  const args = parseArgs(entry.toolArgs);
  const fileContent = (args.content ?? args.file_text) as string | undefined;
  const lang = detectLanguage(filePath);

  return (
    <div className="px-3 py-1.5 text-xs">
      <div className="flex items-center gap-2 text-muted-foreground">
        <FilePlus size={10} className="text-green-400 shrink-0" />
        <span>Created</span>
        {entry.toolDurationMs != null && (
          <span className="text-[10px] opacity-40">{formatDuration(entry.toolDurationMs)}</span>
        )}
      </div>
      {fileContent ? (
        <div className="mt-1 border-l-2 border-green-500/30">
          <SyntaxBlock content={trimWorktreePaths(fileContent)} language={lang} maxLength={800} />
        </div>
      ) : entry.toolResult ? (
        <div className="mt-1 font-mono">
          <TruncatedPayload content={trimWorktreePaths(entry.toolResult)} maxLength={400} />
        </div>
      ) : null}
    </div>
  );
}

function SearchPreview({ entries }: { entries: TranscriptEntry[] }) {
  const entry = entries[entries.length - 1]!;
  const lines = entry.toolResult?.split("\n").filter((l) => l.trim()).length;

  return (
    <div className="text-[13px] sm:text-xs">
      {lines != null && (
        <div className="px-3 py-1 text-muted-foreground/60">→ {lines} results</div>
      )}
      {entry.toolResult && (
        <SyntaxBlock content={trimWorktreePaths(entry.toolResult)} maxLength={600} />
      )}
    </div>
  );
}

function GenericPreview({ entries }: { entries: TranscriptEntry[] }) {
  const entry = entries[entries.length - 1]!;
  return (
    <div className="px-3 py-1.5 text-[13px] sm:text-xs">
      {entry.toolDisplay && (
        <div className="text-muted-foreground mb-1">{entry.toolDisplay}</div>
      )}
      {entry.toolResult && (
        <SyntaxBlock content={trimWorktreePaths(entry.toolResult)} maxLength={400} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feed item renderers
// ---------------------------------------------------------------------------

const OperatorMessage = memo(function OperatorMessage({ entry }: { entry: TranscriptEntry }) {
  return (
    <div className="flex gap-2 sm:gap-3 py-3">
      <div className="shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-primary/15 flex items-center justify-center">
        <User size={13} className="text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <HighlightedMarkdown content={entry.content ?? ""} />
      </div>
    </div>
  );
});

const AgentTurnBlock = memo(function AgentTurnBlock({
  turn,
  clusters,
  sdk,
  isStreaming,
  streamingText,
  streamingReasoningText,
  onViewStepChanges,
}: {
  turn: AgentTurn;
  clusters: ActionCluster[];
  sdk?: string;
  isStreaming?: boolean;
  streamingText?: string;
  streamingReasoningText?: string;
  onViewStepChanges?: (filePaths: string[], label: string, scrollToSeq?: number, turnId?: string) => void;
}) {
  const hasTools = clusters.length > 0;
  const messageContent = turn.message?.content?.trim() ?? "";
  const displayMessage = streamingText || messageContent;
  const hasMessage = !!displayMessage;
  const hasReasoning = !!(turn.reasoning?.content || streamingReasoningText);

  return (
    <div className="py-3 space-y-2">
      {/* Tool phases as stacked boxes */}
      {hasTools && (
        <div className="space-y-1.5">
          {clusters.map((c, i) => {
            if (c.kind === "agent") {
              return <SubAgentBubble key={i} cluster={c} sdk={sdk} />;
            }
            return (
              <PhaseBox
                key={i}
                cluster={c}
                defaultExpanded={true}
                onViewStepChanges={onViewStepChanges}
              />
            );
          })}
        </div>
      )}

      {/* Agent bubble — message + reasoning grouped together */}
      {(hasMessage || (hasReasoning && !hasTools)) && (
        <div className="flex gap-2 sm:gap-3">
          {/* Phase 1: Agent identity avatar */}
          <div className="shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-muted/50 border border-border/30 flex items-center justify-center mt-0.5">
            <SdkIcon sdk={sdk} size={14} fallback={<Bot size={13} className="text-muted-foreground/60" />} />
          </div>
          <div className={cn(
            "flex-1 min-w-0 rounded-lg px-2.5 sm:px-3 py-2 space-y-1.5",
            isStreaming ? "bg-primary/5" : "bg-muted/5",
          )}>
            {/* Reasoning — expandable inside the bubble */}
            {hasReasoning && (
              <ReasoningHint content={turn.reasoning?.content ?? ""} streamingText={streamingReasoningText} />
            )}

            {/* Agent message — the high-signal content */}
            {displayMessage && (
              <div className="text-[15px] sm:text-sm text-foreground/90 leading-relaxed">
                <HighlightedMarkdown content={displayMessage} />
                {isStreaming && (
                  <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5 align-text-bottom" />
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reasoning only (no message yet, but tools present) — show below tools */}
      {hasReasoning && hasTools && !hasMessage && (
        <ReasoningHint content={turn.reasoning?.content ?? ""} streamingText={streamingReasoningText} />
      )}

      {/* Streaming with no committed message yet and no reasoning bubble shown */}
      {!displayMessage && isStreaming && streamingText && !hasReasoning && (
        <div className="flex gap-2 sm:gap-3">
          <div className="shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-muted/50 border border-border/30 flex items-center justify-center mt-0.5">
            <SdkIcon sdk={sdk} size={14} fallback={<Bot size={13} className="text-muted-foreground/60" />} />
          </div>
          <div className="flex-1 min-w-0 rounded-lg bg-primary/5 px-3 py-2">
            <div className="text-[15px] sm:text-sm text-foreground/90 leading-relaxed">
              <HighlightedMarkdown content={streamingText} />
              <span className="inline-block w-1.5 h-4 bg-primary/60 animate-pulse ml-0.5 align-text-bottom" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

const CondensedTurnBlock = memo(function CondensedTurnBlock({
  turn,
  clusters,
  sdk,
  onViewStepChanges,
}: {
  turn: AgentTurn;
  clusters: ActionCluster[];
  sdk?: string;
  onViewStepChanges?: (filePaths: string[], label: string, scrollToSeq?: number, turnId?: string) => void;
}) {
  // Condensed turns (no agent message) — show phases collapsed
  return (
    <div className="py-1 space-y-1">
      {clusters.map((c, i) => (
        c.kind === "agent"
          ? <SubAgentBubble key={i} cluster={c} sdk={sdk} />
          : <PhaseBox key={i} cluster={c} defaultExpanded={true} onViewStepChanges={onViewStepChanges} />
      ))}
      {turn.reasoning?.content && (
        <div className="mt-1">
          <div className="flex-1 min-w-0 rounded-lg bg-muted/5 px-2.5 sm:px-3 py-2">
            <ReasoningHint content={turn.reasoning.content} />
          </div>
        </div>
      )}
    </div>
  );
});

function ReasoningHint({ content, streamingText }: { content: string; streamingText?: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLiveStreaming = !!streamingText && !content;
  const displayContent = streamingText || content;
  // Phase 2: Show 2-3 lines by default (~200 chars) instead of nothing
  const preview = displayContent.length > 200 ? displayContent.slice(0, 200) + "…" : displayContent;
  const isLong = displayContent.length > 200;
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll streaming reasoning to bottom
  useEffect(() => {
    if (isLiveStreaming && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [isLiveStreaming, displayContent]);

  // Auto-expand while streaming, collapse when streaming ends
  const showExpanded = expanded || isLiveStreaming;

  return (
    <div className={cn(
      "text-xs text-foreground/50 leading-snug border-l-2 pl-2.5",
      isLiveStreaming ? "animate-reasoning-pulse" : "border-primary/15",
    )}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-start gap-1.5 hover:text-foreground/70 transition-colors text-left w-full"
      >
        <Brain size={14} className="shrink-0 mt-0.5 text-primary/40" />
        {showExpanded ? (
          <div ref={scrollRef} className="whitespace-pre-wrap max-h-48 overflow-y-auto flex-1 min-w-0 italic">
            {trimWorktreePaths(displayContent)}
            {isLiveStreaming && (
              <span className="inline-block w-1 h-3 bg-primary/50 animate-pulse ml-0.5 align-text-bottom" />
            )}
          </div>
        ) : (
          <div className="flex-1 min-w-0">
            <span className="line-clamp-3 italic">{preview}</span>
            {isLong && <span className="text-primary/40 text-[10px] ml-1">Show more</span>}
          </div>
        )}
      </button>
    </div>
  );
}

function InlineApprovalCard({ approval }: { approval: ApprovalRequest }) {
  const [resolving, setResolving] = useState<"approved" | "rejected" | null>(null);

  const handleResolve = async (resolution: "approved" | "rejected") => {
    setResolving(resolution);
    try {
      await resolveApproval(approval.id, resolution);
    } catch (err) {
      toast.error("Failed to resolve approval");
      console.error(err);
    } finally {
      setResolving(null);
    }
  };

  const isResolved = !!approval.resolvedAt;

  return (
    <div className={cn(
      "rounded-lg border px-4 py-3 my-2",
      isResolved ? "border-border/40 bg-card/30" : "border-amber-600/30 bg-amber-950/10",
    )}>
      <div className="flex items-start gap-2.5">
        <ShieldQuestion size={15} className={cn("shrink-0 mt-0.5", isResolved ? "text-muted-foreground/40" : "text-amber-400")} />
        <div className="flex-1 min-w-0 space-y-2">
          <p className="text-sm text-foreground/80">{approval.description}</p>
          {approval.proposedAction && (
            <pre className="text-[11px] text-muted-foreground/60 bg-black/20 rounded px-2 py-1 whitespace-pre-wrap max-h-24 overflow-auto">
              {approval.proposedAction}
            </pre>
          )}
          {isResolved ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground/50">
              {approval.resolution === "approved"
                ? <><CheckCircle2 size={12} className="text-emerald-400/60" /> Approved</>
                : <><XCircleIcon size={12} className="text-red-400/60" /> Rejected</>
              }
            </div>
          ) : (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleResolve("approved")}
                disabled={!!resolving}
                className="text-xs h-7 sm:h-7 min-h-[44px] sm:min-h-0 border-emerald-700/40 text-emerald-400 hover:bg-emerald-950/30"
              >
                {resolving === "approved" ? <Spinner className="w-3 h-3" /> : "Approve"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleResolve("rejected")}
                disabled={!!resolving}
                className="text-xs h-7 sm:h-7 min-h-[44px] sm:min-h-0 border-red-700/40 text-red-400 hover:bg-red-950/30"
              >
                {resolving === "rejected" ? <Spinner className="w-3 h-3" /> : "Reject"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DividerLine({ entry }: { entry: TranscriptEntry }) {
  const text = entry.content || "Session";
  const isStep = text !== "Session";
  return (
    <div className="flex items-center gap-2.5 py-4">
      <div className="flex-1 border-t border-border/50" />
      <div className="flex items-center gap-1.5 shrink-0">
        {isStep ? (
          <CheckCircle2 size={12} className="text-emerald-400/70" />
        ) : (
          <Milestone size={12} className="text-muted-foreground/40" />
        )}
        <span className={cn(
          "text-[11px] font-medium tracking-wide",
          isStep ? "text-foreground/60" : "text-muted-foreground/40 uppercase",
        )}>
          {text}
        </span>
      </div>
      <div className="flex-1 border-t border-border/50" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent activity pulse bar — ambient heartbeat when agent is working
// ---------------------------------------------------------------------------

function AgentActivityBar({ jobId, sdk, jobState }: { jobId: string; sdk?: string; jobState?: string }) {
  const job = useStore((s) => s.jobs[jobId]);
  const streamingMessages = useStore((s) => s.streamingMessages);
  const isJobLive = jobState === "running" || jobState === "waiting_for_approval";

  // Hide when not live, or when agent is actively streaming a message
  const hasStream = Object.keys(streamingMessages).some((k) => k.startsWith(`${jobId}:`));
  if (!isJobLive || hasStream) return null;

  const headline = job?.progressHeadline || "Working\u2026";
  const isApproval = jobState === "waiting_for_approval";

  return (
    <div className="animate-activity-shimmer rounded-md border border-border/30 px-3 py-2 mb-1 flex items-center gap-2.5 transition-opacity duration-300">
      <div className="relative shrink-0">
        <SdkIcon sdk={sdk} size={14} fallback={<Bot size={13} className="text-muted-foreground/60" />} />
        <span className={cn(
          "absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full",
          isApproval ? "bg-amber-400 animate-pulse" : "bg-emerald-400",
        )} style={{ animationDuration: "2s" }} />
      </div>
      <span className="text-xs text-muted-foreground/70 truncate flex-1 min-w-0">{headline}</span>
      <Clock size={10} className="text-muted-foreground/30 shrink-0" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CuratedFeed({
  jobId,
  sdk,
  interactive,
  pausable,
  jobState,
  prompt,
  promptTimestamp,
  onViewStepChanges,
  onSearchHighlight,
  scrollToSeq,
  scrollToTurnId,
}: {
  jobId: string;
  sdk?: string;
  interactive?: boolean;
  pausable?: boolean;
  jobState?: string;
  prompt?: string;
  promptTimestamp?: string;
  onViewStepChanges?: (filePaths: string[], label: string, scrollToSeq?: number, turnId?: string) => void;
  onSearchHighlight?: (turnId: string | null) => void;
  scrollToSeq?: number | null;
  scrollToTurnId?: string | null;
}) {
  const navigate = useNavigate();
  const rawEntries = useStore(selectJobTranscript(jobId));
  const allApprovals = useStore(selectApprovals);
  const streamingMessages = useStore((s) => s.streamingMessages);
  const allStreamingReasoning = useStore((s) => s.streamingReasoning);
  const jobApprovals = Object.values(allApprovals).filter((a) => a.jobId === jobId);
  const isJobLive = jobState === "running" || jobState === "waiting_for_approval";

  const entries = useMemo<TranscriptEntry[]>(() => [
    ...(prompt
      ? [{ jobId, seq: -1, timestamp: promptTimestamp ?? "", role: "operator", content: prompt }]
      : []),
    ...rawEntries.filter((e) => {
      if (!e.content?.trim() && e.role !== "tool_call" && e.role !== "tool_running") return false;
      if (prompt && e.role === "operator" && e.content === prompt) return false;
      return true;
    }),
  ], [rawEntries, jobId, prompt, promptTimestamp]);

  const feedItems = useMemo(
    () => buildFeedItems(entries, jobApprovals),
    [entries, jobApprovals],
  );

  // Virtualizer — NO auto-scroll. User controls scroll at all times.
  const viewportRef = useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const virtualizer = useVirtualizer({
    count: feedItems.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => 120,
    overscan: 5,
  });

  // Phase 2: Track which feed items existed at hydration time.
  // Items appended after this threshold get entrance animations.
  const hydratedCountRef = useRef(feedItems.length);
  useEffect(() => {
    // On initial load / job change, snapshot the count as "already seen"
    hydratedCountRef.current = feedItems.length;
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to a specific feed item when scrollToSeq is set (from diff tab "back to step" link)
  // This is the ONLY programmatic scroll — explicit user-initiated navigation.
  const [highlightIdx, setHighlightIdx] = useState<number | null>(null);
  const handledSeqRef = useRef<number | null>(null);
  useEffect(() => {
    if (scrollToSeq == null) { handledSeqRef.current = null; return; }
    if (feedItems.length === 0) return;
    if (handledSeqRef.current === scrollToSeq) return;
    const idx = feedItems.findIndex((item) => {
      if (item.type === "turn" || item.type === "condensed") {
        return item.turn.toolCalls.some((tc) => tc.seq === scrollToSeq);
      }
      if (item.type === "operator" || item.type === "divider") {
        return item.entry.seq === scrollToSeq;
      }
      return false;
    });
    if (idx >= 0) {
      handledSeqRef.current = scrollToSeq;
      virtualizer.scrollToIndex(idx, { align: "start", behavior: "smooth" });
      setTimeout(() => setHighlightIdx(idx), 300);
    }
  }, [scrollToSeq, feedItems, virtualizer]);

  // Scroll to a specific turn when scrollToTurnId is set (from activity timeline click)
  const handledTurnIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (scrollToTurnId == null) { handledTurnIdRef.current = null; return; }
    if (feedItems.length === 0) return;
    if (handledTurnIdRef.current === scrollToTurnId) return;
    let idx = feedItems.findIndex((item) => {
      if (item.type === "turn" || item.type === "condensed") {
        return item.turn.turnId === scrollToTurnId;
      }
      return false;
    });
    if (idx >= 0) {
      handledTurnIdRef.current = scrollToTurnId;
      virtualizer.scrollToIndex(idx, { align: "start", behavior: "smooth" });
      // Delay highlight slightly so user can track the smooth scroll
      setTimeout(() => setHighlightIdx(idx), 300);
    }
  }, [scrollToTurnId, feedItems, virtualizer]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setShowScrollBtn(!atBottom);
  };

  const scrollToBottom = useCallback(() => {
    if (feedItems.length > 0) {
      virtualizer.scrollToIndex(feedItems.length - 1, { align: "end", behavior: "smooth" });
      setShowScrollBtn(false);
    }
  }, [feedItems.length, virtualizer]);

  // Message composer state
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const waveformContainerRef = useRef<HTMLDivElement>(null);

  const isReview = jobState === "review";
  const isTerminal = ["completed", "failed", "canceled"].includes(jobState ?? "");

  const handleSend = useCallback(async () => {
    if (!msg.trim() || !jobId || sending) return;
    const text = msg.trim();
    setMsg("");
    setSending(true);
    try {
      if (isTerminal) {
        // Create a new follow-up job for truly terminal states
        const followup = await continueJob(jobId, text);
        toast.success("Follow-up job started");
        navigate(`/jobs/${followup.id}`);
      } else if (isReview) {
        // Review state: try sendOperatorMessage first — it handles both
        // "actually running" (stale frontend state) and "needs resume"
        // (auto-resume via _resume_orphaned) on the backend.  Only fall
        // back to the explicit resumeJob path when that fails.
        try {
          await sendOperatorMessage(jobId, text);
        } catch {
          await resumeJob(jobId, text);
          toast.success("Job resumed");
        }
      } else {
        await sendOperatorMessage(jobId, text);
      }
    } catch (err) {
      setMsg(text);
      const detail =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Unknown error";
      toast.error(`Failed to send: ${detail}`);
      console.error(err);
    } finally {
      setSending(false);
    }
  }, [msg, jobId, sending, isReview, isTerminal, navigate]);

  const handlePause = useCallback(async () => {
    if (!jobId) return;
    setPausing(true);
    try {
      await pauseJob(jobId);
      toast.info("Agent paused");
    } catch (err) {
      toast.error("Failed to pause");
      console.error(err);
    } finally {
      setPausing(false);
    }
  }, [jobId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Search: compute a Set of matching feed-item indices.
  // The virtualizer always iterates ALL feedItems — we just hide non-matches via CSS.
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(searchQuery), 150);
    return () => clearTimeout(t);
  }, [searchQuery]);

  const matchingIndices = useMemo<Set<number> | null>(() => {
    const q = debouncedQuery.trim().toLowerCase();
    if (!q) return null; // null = show all
    const set = new Set<number>();
    feedItems.forEach((item, idx) => {
      let match = false;
      if (item.type === "operator") match = !!item.entry.content?.toLowerCase().includes(q);
      else if (item.type === "turn" || item.type === "condensed") {
        const turn = item.turn;
        match = !!(turn.message?.content?.toLowerCase().includes(q)
          || turn.reasoning?.content?.toLowerCase().includes(q)
          || turn.toolCalls.some((t) =>
            t.toolDisplay?.toLowerCase().includes(q)
            || t.toolName?.toLowerCase().includes(q)
          )
        );
      } else if (item.type === "approval") match = item.approval.description.toLowerCase().includes(q);
      else match = true; // dividers: show if adjacent matches (keep it simple — show all dividers)
      if (match) set.add(idx);
    });
    return set;
  }, [feedItems, debouncedQuery]);

  const matchCount = matchingIndices !== null ? matchingIndices.size : null;
  const activeHighlight = debouncedQuery.trim().toLowerCase();

  // Sorted array of matching feed-item indices for next/prev navigation
  const EMPTY_MATCH_LIST: number[] = [];
  const matchList = useMemo(() => {
    if (!matchingIndices || matchingIndices.size === 0) return EMPTY_MATCH_LIST;
    return Array.from(matchingIndices).sort((a, b) => a - b);
  }, [matchingIndices]); // eslint-disable-line react-hooks/exhaustive-deps

  const [currentMatchPos, setCurrentMatchPos] = useState(0); // position within matchList

  // Auto-jump to first match when search query produces results.
  // Uses debouncedQuery as trigger so it fires once per distinct query.
  // Extract the turnId from a feedItem at a given index.
  // If the item itself isn't a turn (e.g. operator message), walk backwards
  // to find the nearest preceding turn — that's the activity context.
  const getTurnIdForIndex = useCallback((idx: number): string | null => {
    for (let i = idx; i >= 0; i--) {
      const item = feedItems[i];
      if (!item) continue;
      if (item.type === "turn" || item.type === "condensed") {
        return item.turn.turnId ?? null;
      }
    }
    return null;
  }, [feedItems]);

  // Stable refs for callbacks used in search effects — avoids stale closures
  const onSearchHighlightRef = useRef(onSearchHighlight);
  onSearchHighlightRef.current = onSearchHighlight;
  const getTurnIdForIndexRef = useRef(getTurnIdForIndex);
  getTurnIdForIndexRef.current = getTurnIdForIndex;

  const lastJumpedQueryRef = useRef("");
  useEffect(() => {
    const q = debouncedQuery.trim();
    if (!q) { lastJumpedQueryRef.current = ""; onSearchHighlightRef.current?.(null); return; }
    if (matchList.length === 0) return;
    if (lastJumpedQueryRef.current === q) return; // already jumped for this query
    lastJumpedQueryRef.current = q;
    setCurrentMatchPos(0);
    const first = matchList[0]!;
    virtualizer.scrollToIndex(first, { align: "center" });
    setHighlightIdx(first);
    onSearchHighlightRef.current?.(getTurnIdForIndexRef.current(first));
  }, [debouncedQuery, matchList]); // eslint-disable-line react-hooks/exhaustive-deps

  const jumpToMatch = useCallback((pos: number) => {
    if (matchList.length === 0) return;
    const clamped = ((pos % matchList.length) + matchList.length) % matchList.length;
    setCurrentMatchPos(clamped);
    const feedIdx = matchList[clamped]!;
    virtualizer.scrollToIndex(feedIdx, { align: "center" });
    setHighlightIdx(feedIdx);
    onSearchHighlightRef.current?.(getTurnIdForIndexRef.current(feedIdx));
  }, [matchList, virtualizer]);

  const nextMatch = useCallback(() => jumpToMatch(currentMatchPos + 1), [jumpToMatch, currentMatchPos]);
  const prevMatch = useCallback(() => jumpToMatch(currentMatchPos - 1), [jumpToMatch, currentMatchPos]);

  // Ctrl+F / ⌘+F to open search
  const searchInputRef = useRef<HTMLInputElement>(null);
  useHotkeys("mod+f", (e) => { e.preventDefault(); setSearchOpen(true); setTimeout(() => searchInputRef.current?.focus(), 0); }, { enableOnFormTags: true });
  useHotkeys("Escape", () => { if (searchOpen) { setSearchOpen(false); setSearchQuery(""); onSearchHighlightRef.current?.(null); } }, { enableOnFormTags: true });

  return (
    <div className="flex flex-col h-full relative">
      {/* Virtualized feed — search is integrated at the top */}
      <div
        ref={viewportRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto rounded-lg border border-border bg-card"
      >
        {/* Inline search — sticky so it stays visible on scroll */}
        <div className="sticky top-0 z-10 px-3 sm:px-4 pt-2.5 pb-6" style={{ background: "linear-gradient(to bottom, hsl(var(--card)) 40%, hsl(var(--card) / 0) 100%)" }}>
          <div
            className={cn(
              "flex items-center gap-2 transition-colors cursor-text",
              searchOpen ? "text-foreground" : "text-muted-foreground/40 hover:text-muted-foreground/60",
            )}
            onClick={() => { if (!searchOpen) { setSearchOpen(true); setTimeout(() => searchInputRef.current?.focus(), 0); } }}
          >
            <Search size={13} className="shrink-0" />
            {searchOpen ? (
              <>
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { e.preventDefault(); if (e.shiftKey) { prevMatch(); } else { nextMatch(); } }
                  }}
                  placeholder="Search transcript…"
                  className="flex-1 bg-transparent text-base sm:text-sm text-foreground outline-none placeholder:text-muted-foreground/40"
                  autoFocus
                />
                {matchCount !== null && (
                  <span className="text-[11px] tabular-nums text-muted-foreground/60 shrink-0">
                    {matchCount > 0 ? `${currentMatchPos + 1}/${matchCount}` : "0 results"}
                  </span>
                )}
                {matchCount !== null && matchCount > 0 && (
                  <div className="flex items-center shrink-0">
                    <button onClick={prevMatch} className="p-1.5 min-h-[44px] min-w-[32px] flex items-center justify-center text-muted-foreground/50 hover:text-muted-foreground" aria-label="Previous match">
                      <ChevronUp size={14} />
                    </button>
                    <button onClick={nextMatch} className="p-1.5 min-h-[44px] min-w-[32px] flex items-center justify-center text-muted-foreground/50 hover:text-muted-foreground" aria-label="Next match">
                      <ChevronDown size={14} />
                    </button>
                  </div>
                )}
                <button onClick={() => { setSearchOpen(false); setSearchQuery(""); onSearchHighlightRef.current?.(null); }} className="p-1.5 min-h-[44px] sm:min-h-0 min-w-[44px] sm:min-w-0 flex items-center justify-center text-muted-foreground/40 hover:text-muted-foreground shrink-0">
                  <X size={14} />
                </button>
              </>
            ) : (
              <>
                <span className="flex-1 text-base sm:text-sm">Search…</span>
                <kbd className="hidden sm:inline text-[10px] text-muted-foreground/30 font-mono shrink-0">{navigator.platform.includes("Mac") ? "⌘" : "Ctrl"}+F</kbd>
              </>
            )}
          </div>
          {/* Divider line with margin on both sides */}
          <div className="mx-2 mt-2.5 mb-1 border-b border-border/40" />
        </div>

        <div
          style={{ height: virtualizer.getTotalSize(), position: "relative" }}
        >
          {virtualizer.getVirtualItems().map((vItem) => {
            const item = feedItems[vItem.index];
            if (!item) return null;
            // When searching, dim non-matching items instead of hiding them
            // (hiding breaks virtualizer position calculations)
            const dimmed = matchingIndices !== null && !matchingIndices.has(vItem.index);
            const isActiveMatch = vItem.index === highlightIdx;
            // Phase 2: Entrance animation for items appended after hydration
            const isNew = vItem.index >= hydratedCountRef.current;

            return (
              <div
                key={vItem.key}
                ref={virtualizer.measureElement}
                data-index={vItem.index}
                className={cn(
                  isActiveMatch && "animate-glow-flicker",
                  isNew && !isActiveMatch && "animate-feed-enter",
                )}
                onAnimationEnd={isActiveMatch ? () => setHighlightIdx(null) : undefined}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${vItem.start}px)`,
                  ...(dimmed ? { opacity: 0.15, pointerEvents: "none" as const } : {}),
                }}
              >
                <div className="px-3 sm:px-4 overflow-x-hidden">
                  <SearchHighlightCtx.Provider value={activeHighlight}>
                    <FeedItemRenderer
                      item={item}
                      jobId={jobId}
                      sdk={sdk}
                      streamingMessages={streamingMessages}
                      streamingReasoning={allStreamingReasoning}
                      isJobLive={isJobLive}
                      onViewStepChanges={onViewStepChanges}
                    />
                  </SearchHighlightCtx.Provider>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Scroll-to-bottom */}
      {showScrollBtn && (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 z-10">
          <button
            onClick={scrollToBottom}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-card/90 border border-border/50 text-xs text-muted-foreground shadow-lg hover:text-foreground transition-colors"
          >
            <ArrowDown size={12} />
            Jump to bottom
          </button>
        </div>
      )}

      {/* Phase 1: Agent activity pulse — ambient heartbeat between turns */}
      <AgentActivityBar jobId={jobId} sdk={sdk} jobState={jobState} />

      {/* Phase 1: Stateful message composer */}
      {interactive && (
        <div className={cn(
          "rounded-lg border bg-card px-3 py-2 mt-1 transition-colors",
          jobState === "waiting_for_approval" ? "border-amber-600/40" :
          isReview ? "border-primary/40" :
          isTerminal ? "border-border border-dashed" :
          "border-border",
        )}>
          <div className="flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea
                value={msg}
                onChange={(e) => setMsg(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  jobState === "waiting_for_approval" ? "The agent needs your decision above \u2191" :
                  isReview ? "Send follow-up to resume\u2026" :
                  isTerminal ? "Start a follow-up job\u2026" :
                  "Message the agent\u2026"
                }
                rows={1}
                className="w-full resize-none bg-transparent text-base sm:text-sm text-foreground placeholder:text-muted-foreground/30 outline-none py-2 pr-8 max-h-32"
                style={{ minHeight: "2.25rem" }}
                disabled={sending}
              />
              <div ref={waveformContainerRef} />
            </div>
            <div className="flex items-center gap-1 pb-1.5">
              <MicButton
                onStateChange={() => {}}
                waveformContainerRef={waveformContainerRef}
                onTranscript={(text: string) => setMsg((prev: string) => prev + text)}
              />
              {pausable && isJobLive && jobState === "running" && (
                <button
                  onClick={handlePause}
                  disabled={pausing}
                  className="p-1.5 text-muted-foreground/40 hover:text-amber-400 transition-colors"
                  title="Pause agent"
                >
                  <PauseCircle size={15} />
                </button>
              )}
              <button
                onClick={handleSend}
                disabled={!msg.trim() || sending}
                className={cn(
                  "p-1.5 rounded-md transition-colors",
                  msg.trim() ? "text-primary hover:bg-primary/10" : "text-muted-foreground/20",
                )}
                title={isReview ? "Resume job" : isTerminal ? "Create follow-up job" : "Send message"}
              >
                {sending ? <Spinner className="w-4 h-4" /> : <Send size={15} />}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Feed item dispatch
// ---------------------------------------------------------------------------

const FeedItemRenderer = memo(function FeedItemRenderer({
  item,
  jobId,
  sdk,
  streamingMessages,
  streamingReasoning,
  isJobLive,
  onViewStepChanges,
}: {
  item: FeedItem;
  jobId: string;
  sdk?: string;
  streamingMessages: Record<string, string>;
  streamingReasoning: Record<string, string>;
  isJobLive: boolean;
  onViewStepChanges?: (filePaths: string[], label: string, scrollToSeq?: number, turnId?: string) => void;
}) {
  switch (item.type) {
    case "operator":
      return <OperatorMessage entry={item.entry} />;
    case "turn": {
      const streamKey = item.turn.turnId ? `${jobId}:${item.turn.turnId}` : `${jobId}:__default__`;
      const streamingText = isJobLive ? streamingMessages[streamKey] : undefined;
      const streamingReasoningText = isJobLive ? streamingReasoning[streamKey] : undefined;
      const isStreaming = !!streamingText && !item.turn.message?.content;
      return (
        <AgentTurnBlock
          turn={item.turn}
          clusters={item.clusters}
          sdk={sdk}
          isStreaming={isStreaming}
          streamingText={streamingText}
          streamingReasoningText={streamingReasoningText}
          onViewStepChanges={onViewStepChanges}
        />
      );
    }
    case "condensed":
      return <CondensedTurnBlock turn={item.turn} clusters={item.clusters} sdk={sdk} onViewStepChanges={onViewStepChanges} />;
    case "approval":
      return <InlineApprovalCard approval={item.approval} />;
    case "divider":
      return <DividerLine entry={item.entry} />;
    default:
      return null;
  }
});
