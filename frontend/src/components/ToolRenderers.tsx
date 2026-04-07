import { useState } from "react";
import { ChevronDown, Network, Brain } from "lucide-react";
import { cn } from "../lib/utils";
import { Codicon } from "./ui/codicon";
import { resolveToolIcon, type ToolIconDef } from "../lib/toolIcons";
import type { TranscriptEntry } from "../store";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function prettifyJson(raw: string | undefined): string {
  if (!raw) return "";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function stripMcpPrefix(name: string): string {
  return name.includes("/") ? name.split("/").pop()! : name;
}

export function parseArgs(toolArgs?: string): Record<string, unknown> {
  if (!toolArgs) return {};
  try {
    const parsed = JSON.parse(toolArgs);
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

export function countLines(text?: string): number | undefined {
  if (!text) return undefined;
  return text.split("\n").filter((l) => l.trim()).length;
}

const WORKTREE_MARKER = "/.codeplane-worktrees/";

export function abbreviatePath(path: string): string {
  const idx = path.indexOf(WORKTREE_MARKER);
  if (idx !== -1) return "…/" + path.slice(idx + WORKTREE_MARKER.length);
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.length <= 2 ? path : parts.slice(-2).join("/");
}

export function trimWorktreePaths(text: string): string {
  return text.replace(/\/[^\s]*\.codeplane-worktrees\//g, "…/");
}

// ---------------------------------------------------------------------------
// TruncatedPayload
// ---------------------------------------------------------------------------

export function TruncatedPayload({ content, maxLength = 500 }: { content: string; maxLength?: number }) {
  const [expanded, setExpanded] = useState(false);
  if (!content || content.length <= maxLength) return <pre className="text-xs whitespace-pre-wrap break-all">{content}</pre>;
  return (
    <div>
      <pre className="text-xs whitespace-pre-wrap break-all">
        {expanded ? content : content.slice(0, maxLength) + "…"}
      </pre>
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-primary hover:underline mt-1"
      >
        {expanded ? "Show less" : `Show all (${content.length.toLocaleString()} chars)`}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReasoningBlock
// ---------------------------------------------------------------------------

export function ReasoningBlock({ entry }: { entry: TranscriptEntry }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 overflow-hidden mb-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <Brain size={11} className="shrink-0 text-violet-400/80" />
        <span className="font-medium">Reasoning</span>
        <ChevronDown
          size={11}
          className={cn("ml-auto shrink-0", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="px-3 pb-2 text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed border-t border-border/50 pt-2 font-mono">
          {entry.content}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StructuredToolContent — per-tool-type renderers
// ---------------------------------------------------------------------------

export function StructuredToolContent({ entry }: { entry: TranscriptEntry }) {
  const toolName = stripMcpPrefix(entry.toolName ?? "");
  const args = parseArgs(entry.toolArgs);

  switch (toolName) {
    case "Bash":
    case "bash":
    case "run_in_terminal": {
      const command = trimWorktreePaths((args.command as string) ?? "");
      return (
        <div className="font-mono text-xs">
          <div className={cn(
            "px-3 py-1.5 border-b border-border/30",
            entry.toolSuccess === false ? "bg-red-950/30" : "bg-zinc-950/50",
          )}>
            <span className="text-muted-foreground">$ </span>
            <span className="text-foreground/90">{command}</span>
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={600} />
            </div>
          )}
        </div>
      );
    }
    case "Read":
    case "read_file": {
      const filePath = (args.filePath ?? args.file_path ?? args.path ?? "") as string;
      const startLine = (args.startLine ?? args.start_line) as number | undefined;
      const endLine = (args.endLine ?? args.end_line) as number | undefined;
      const lines = countLines(entry.toolResult);
      const shortPath = abbreviatePath(filePath);
      const range = startLine && endLine ? `lines ${startLine}–${endLine}` : null;
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="file-code" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">{shortPath}</span>
            {range && <span className="text-muted-foreground">{range}</span>}
            {lines != null && <span className="text-muted-foreground/60">({lines} lines)</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={800} />
            </div>
          )}
        </div>
      );
    }
    case "replace_string_in_file":
    case "str_replace_based_edit_tool":
    case "str_replace_editor":
    case "edit":
    case "Edit":
    case "insert_edit_into_file": {
      const filePath = (args.filePath ?? args.file_path ?? args.path ?? "") as string;
      const shortPath = abbreviatePath(filePath);
      const oldStr = (args.old_str ?? args.old_string ?? args.oldString) as string | undefined;
      const newStr = (args.new_str ?? args.new_string ?? args.newString) as string | undefined;
      return (
        <div className="px-3 py-1.5 text-xs">
          <div className="flex items-center gap-2">
            <Codicon name="edit" size={11} className="text-amber-400 shrink-0" />
            <span className="font-mono text-foreground/80">{shortPath}</span>
            <span className="text-muted-foreground">
              {entry.toolSuccess !== false ? "→ applied" : "→ failed"}
            </span>
          </div>
          {typeof oldStr === "string" && typeof newStr === "string" && (
            <div className="mt-1.5 font-mono text-[11px] leading-relaxed pl-5">
              <div className="text-red-400/80">- {oldStr.slice(0, 80)}{oldStr.length > 80 ? "…" : ""}</div>
              <div className="text-green-400/80">+ {newStr.slice(0, 80)}{newStr.length > 80 ? "…" : ""}</div>
            </div>
          )}
        </div>
      );
    }
    case "multi_replace_string_in_file":
    case "MultiEdit": {
      const edits = (args.replacements ?? args.edits ?? []) as Array<Record<string, unknown>>;
      const paths: string[] = [...new Set(
        edits
          .map((e) => (e.filePath ?? e.file_path ?? e.path ?? "") as string)
          .filter(Boolean)
          .map((p) => abbreviatePath(p)),
      )];
      const label = paths.length
        ? paths.slice(0, 3).join(", ") + (paths.length > 3 ? "…" : "")
        : `${edits.length} location${edits.length !== 1 ? "s" : ""}`;
      return (
        <div className="px-3 py-1.5 text-xs">
          <div className="flex items-center gap-2">
            <Codicon name="edit" size={11} className="text-amber-400 shrink-0" />
            <span className="font-mono text-foreground/80">{label}</span>
            <span className="text-muted-foreground">
              {entry.toolSuccess !== false ? "→ applied" : "→ failed"}
            </span>
          </div>
          {edits.slice(0, 3).map((e, i) => {
            const p = abbreviatePath((e.filePath ?? e.file_path ?? e.path ?? "") as string);
            const oldStr = (e.old_string ?? e.old_str ?? e.oldString) as string | undefined;
            const newStr = (e.new_string ?? e.new_str ?? e.newString) as string | undefined;
            return (
              <div key={i} className="mt-1.5 pl-5">
                {paths.length > 1 && <div className="text-muted-foreground/60 font-mono text-[10px]">{p}</div>}
                {typeof oldStr === "string" && typeof newStr === "string" && (
                  <div className="font-mono text-[11px] leading-relaxed">
                    <div className="text-red-400/80">- {oldStr.slice(0, 80)}{oldStr.length > 80 ? "…" : ""}</div>
                    <div className="text-green-400/80">+ {newStr.slice(0, 80)}{newStr.length > 80 ? "…" : ""}</div>
                  </div>
                )}
              </div>
            );
          })}
          {edits.length > 3 && (
            <div className="mt-1 pl-5 text-muted-foreground/60 text-[10px]">
              +{edits.length - 3} more edit{edits.length - 3 !== 1 ? "s" : ""}
            </div>
          )}
        </div>
      );
    }
    case "grep_search":
    case "semantic_search":
    case "file_search": {
      const query = (args.query ?? args.pattern ?? "") as string;
      const lines = countLines(entry.toolResult);
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="search" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">&ldquo;{query}&rdquo;</span>
            {lines != null && <span className="text-muted-foreground">→ {lines} matches</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={800} />
            </div>
          )}
        </div>
      );
    }
    case "Write":
    case "create_file":
    case "write": {
      const filePath = (args.filePath ?? args.file_path ?? args.path ?? "") as string;
      return (
        <div className="px-3 py-1.5 flex items-center gap-2 text-xs">
          <Codicon name="edit" size={11} className="text-green-400 shrink-0" />
          <span className="font-mono text-foreground/80">{abbreviatePath(filePath)}</span>
          <span className="text-muted-foreground">→ {toolName === "write" || toolName === "Write" ? "written" : "created"}</span>
        </div>
      );
    }
    case "view": {
      const path = (args.path as string) ?? "";
      const viewRange = args.view_range as [number, number] | undefined;
      const lines = countLines(entry.toolResult);
      const range = Array.isArray(viewRange) && viewRange.length >= 2
        ? `lines ${viewRange[0]}–${viewRange[1] === -1 ? "end" : viewRange[1]}`
        : null;
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="file-code" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">{abbreviatePath(path)}</span>
            {range && <span className="text-muted-foreground">{range}</span>}
            {lines != null && <span className="text-muted-foreground/60">({lines} lines)</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={800} />
            </div>
          )}
        </div>
      );
    }
    case "Glob":
    case "glob": {
      const pattern = (args.pattern as string) ?? "";
      const searchPath = (args.path as string) ?? "";
      const lines = countLines(entry.toolResult);
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="search" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">{pattern}</span>
            {searchPath && <span className="text-muted-foreground/60">in {abbreviatePath(searchPath)}</span>}
            {lines != null && <span className="text-muted-foreground">→ {lines} files</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={800} />
            </div>
          )}
        </div>
      );
    }
    case "Grep":
    case "grep": {
      const pattern = (args.pattern ?? args.query ?? "") as string;
      const searchPath = (args.path as string) ?? "";
      const globFilter = (args.glob as string) ?? "";
      const lines = countLines(entry.toolResult);
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="search" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">&ldquo;{pattern}&rdquo;</span>
            {(globFilter || searchPath) && (
              <span className="text-muted-foreground/60">in {globFilter || abbreviatePath(searchPath)}</span>
            )}
            {lines != null && <span className="text-muted-foreground">→ {lines} matches</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={800} />
            </div>
          )}
        </div>
      );
    }
    case "LS":
    case "list_dir": {
      const path = (args.path as string) ?? "";
      const lines = countLines(entry.toolResult);
      return (
        <div className="font-mono text-xs">
          <div className={cn("px-3 py-1.5 flex items-center gap-2", entry.toolResult && "border-b border-border/30")}>
            <Codicon name="file-code" size={11} className="text-blue-400 shrink-0" />
            <span className="text-foreground/80">{abbreviatePath(path) || "."}</span>
            {lines != null && <span className="text-muted-foreground/60">({lines} entries)</span>}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={600} />
            </div>
          )}
        </div>
      );
    }
    case "skill": {
      const skillName = (args.skill as string) ?? "";
      const displayName = skillName
        ? skillName.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
        : (entry.toolTitle ?? entry.toolDisplay ?? entry.toolName ?? "Skill");
      return (
        <div className="font-mono text-xs">
          <div className={cn(
            "px-3 py-1.5 flex items-center gap-2",
            entry.toolResult && "border-b border-border/30",
          )}>
            <Codicon name="robot" size={11} className="text-purple-400 shrink-0" />
            <span className="text-foreground/80">{displayName}</span>
            {entry.toolResult && (
              <span className="text-muted-foreground">
                {entry.toolSuccess !== false ? "→ done" : "→ failed"}
              </span>
            )}
          </div>
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <TruncatedPayload content={entry.toolResult} maxLength={400} />
            </div>
          )}
        </div>
      );
    }
    default:
      return null;
  }
}

export function hasStructuredRenderer(toolName?: string): boolean {
  if (!toolName) return false;
  const name = stripMcpPrefix(toolName);
  return [
    "bash", "run_in_terminal", "Bash",
    "read_file", "Read",
    "replace_string_in_file", "multi_replace_string_in_file", "str_replace_based_edit_tool",
    "str_replace_editor", "edit", "Edit", "insert_edit_into_file", "MultiEdit",
    "create_file", "write", "Write",
    "view",
    "glob", "Glob",
    "grep", "Grep",
    "grep_search", "semantic_search", "file_search",
    "list_dir", "LS",
    "skill",
  ].includes(name);
}

// ---------------------------------------------------------------------------
// ToolDetail — full tool call detail (issue banner + structured + fallback)
// ---------------------------------------------------------------------------

export function ToolDetail({ entry }: { entry: TranscriptEntry }) {
  return (
    <div className="ml-0 mt-1 mb-2 rounded border border-border/40 bg-muted/20 text-xs overflow-hidden">
      {entry.toolSuccess === false && entry.toolIssue && (
        <div className="px-3 py-1.5 bg-red-500/5 border-b border-border/30">
          <span className="text-red-400 font-medium">{entry.toolIssue}</span>
        </div>
      )}
      <StructuredToolContent entry={entry} />
      {!hasStructuredRenderer(entry.toolName) && (
        <>
          {entry.toolArgs && (
            <div className="px-3 py-1.5 border-b border-border/30">
              <span className="text-muted-foreground font-medium text-[10px] uppercase">Input</span>
              <pre className="mt-0.5 whitespace-pre-wrap break-all text-xs">{prettifyJson(entry.toolArgs)}</pre>
            </div>
          )}
          {entry.toolResult && (
            <div className="px-3 py-1.5">
              <span className="text-muted-foreground font-medium text-[10px] uppercase">Output</span>
              <TruncatedPayload content={entry.toolResult} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ToolIconGlyph
// ---------------------------------------------------------------------------

export function ToolIconGlyph({ icon, className }: { icon: ToolIconDef; className?: string }) {
  if (icon.kind === "codicon") {
    return <Codicon name={icon.name} size={13} className={className} />;
  }
  const Icon = icon.icon;
  return <Icon size={13} className={className} />;
}

// ---------------------------------------------------------------------------
// Sub-agent support
// ---------------------------------------------------------------------------

const SUB_AGENT_TOOLS = new Set(["Task", "task", "runSubagent", "search_subagent", "skill"]);

function isSubagentTool(toolName?: string): boolean {
  if (!toolName) return false;
  return SUB_AGENT_TOOLS.has(stripMcpPrefix(toolName));
}

interface ToolSegment {
  type: "standalone" | "subagent-group";
  entry: TranscriptEntry;
  children: TranscriptEntry[];
}

export function groupToolCalls(calls: TranscriptEntry[]): ToolSegment[] {
  const segments: ToolSegment[] = [];
  let i = 0;

  while (i < calls.length) {
    const call = calls[i]!;

    if (isSubagentTool(call.toolName)) {
      const children: TranscriptEntry[] = [];

      if (call.role === "tool_running") {
        i++;
        while (i < calls.length) {
          children.push(calls[i]!);
          i++;
        }
      } else {
        i++;
        if (call.toolDurationMs != null && call.toolDurationMs > 0) {
          const startMs = new Date(call.timestamp).getTime();
          const endMs = startMs + call.toolDurationMs;
          while (i < calls.length) {
            const next = calls[i]!;
            if (isSubagentTool(next.toolName)) break;
            const ts = new Date(next.timestamp).getTime();
            if (ts >= startMs && ts <= endMs + 1000) {
              children.push(next);
              i++;
            } else {
              break;
            }
          }
        }
      }

      segments.push({ type: "subagent-group", entry: call, children });
    } else {
      segments.push({ type: "standalone", entry: call, children: [] });
      i++;
    }
  }

  return segments;
}

function SubAgentResult({ result }: { result: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded border border-border/30 bg-muted/10 overflow-hidden mt-1">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-2.5 py-1 text-left text-[10px] text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
      >
        <Network size={10} className="shrink-0 text-violet-400/60" />
        <span className="font-medium uppercase tracking-wide">Sub-agent Result</span>
        <ChevronDown
          size={9}
          className={cn("ml-auto shrink-0", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="px-2.5 pb-2 pt-1 border-t border-border/20 text-xs">
          <TruncatedPayload content={result} maxLength={600} />
        </div>
      )}
    </div>
  );
}

export function SubAgentSection({
  entry,
  childCalls,
  isActive,
}: {
  entry: TranscriptEntry;
  childCalls: TranscriptEntry[];
  isActive: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const isRunning = entry.role === "tool_running";
  const failed = entry.toolSuccess === false;

  const args = parseArgs(entry.toolArgs);
  const rawLabel = entry.toolDisplayFull
    ?? entry.toolDisplay
    ?? (typeof args.description === "string" ? args.description : null)
    ?? (typeof args.prompt === "string" ? args.prompt : null)
    ?? (typeof args.query === "string" ? args.query : null)
    ?? (typeof args.skill === "string" ? args.skill : null)
    ?? "";
  const description = rawLabel.replace(/^(?:Task|Subagent|Search agent|Skill):\s*/i, "").trim()
    || "Launching Subagent";
  const label = `Task: ${description}`;

  const iconColor = failed ? "text-red-400"
    : isRunning || isActive ? "text-violet-400"
    : "text-violet-400/70";
  const hasContent = childCalls.length > 0 || (!isRunning && entry.toolResult);

  return (
    <div className="relative pl-4 sm:pl-5">
      <div className="absolute left-0 top-[3px] w-[15px] h-[15px] flex items-center justify-center">
        <Network size={13} className={iconColor} />
        {(isActive || isRunning) && (
          <span className="absolute -right-0.5 -top-0.5 w-1.5 h-1.5 rounded-full bg-violet-400" />
        )}
      </div>

      <button
        onClick={() => hasContent && setCollapsed(!collapsed)}
        className={cn("w-full text-left group", !hasContent && "cursor-default")}
      >
        <div className="flex items-baseline gap-2 py-0.5 min-w-0">
          <span className={cn(
            "text-xs font-mono truncate min-w-0 flex-1",
            failed ? "text-red-400"
              : isRunning || isActive ? "text-violet-400"
              : "text-foreground/80",
          )}>
            {label}{isRunning ? "\u2026" : ""}
          </span>
          {entry.toolDurationMs != null && (
            <span className="text-[10px] text-muted-foreground/60 shrink-0">
              {formatDuration(entry.toolDurationMs)}
            </span>
          )}
          {failed && entry.toolIssue && (
            <span className="text-[10px] text-red-400 truncate max-w-[200px] shrink-0">
              {entry.toolIssue}
            </span>
          )}
          {hasContent && (
            <ChevronDown
              size={10}
              className={cn(
                "shrink-0 text-muted-foreground/50",
                !collapsed && "rotate-180",
              )}
            />
          )}
        </div>
      </button>

      {!collapsed && hasContent && (
        <div className="pl-1 sm:pl-1.5 border-l border-violet-500/20 mt-0.5 space-y-0.5">
          {childCalls.map((child, i) =>
            isSubagentTool(child.toolName) ? (
              <SubAgentSection
                key={child.seq}
                entry={child}
                childCalls={[]}
                isActive={isActive && i === childCalls.length - 1}
              />
            ) : (
              <ToolStep
                key={child.seq}
                entry={child}
                isActive={isActive && i === childCalls.length - 1}
              />
            ),
          )}

          {isRunning && childCalls.length === 0 && (
            <div className="text-xs text-violet-400/60 py-0.5 pl-4 sm:pl-5">
              Running\u2026
            </div>
          )}

          {!isRunning && entry.toolResult && (
            <SubAgentResult result={entry.toolResult} />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ToolStep — single tool call with expand-to-detail
// ---------------------------------------------------------------------------

export function ToolStep({ entry, isActive }: {
  entry: TranscriptEntry;
  isActive: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const failed = entry.toolSuccess === false;
  const isRunning = entry.role === "tool_running";
  const label = entry.toolIntent || entry.toolTitle || entry.toolDisplayFull || entry.toolDisplay || entry.toolName || entry.content;
  const icon = resolveToolIcon(entry.toolName);

  return (
    <div className="relative pl-4 sm:pl-5">
      <div className="absolute left-0 top-[3px] w-[15px] h-[15px] flex items-center justify-center">
        <ToolIconGlyph icon={icon} className={cn(
          failed ? "text-red-400"
            : (isActive || isRunning) ? "text-blue-400"
            : "text-muted-foreground/80",
        )} />
        {(isActive || isRunning) && (
          <span className="absolute -right-0.5 -top-0.5 w-1.5 h-1.5 rounded-full bg-blue-400" />
        )}
      </div>
      <button
        onClick={() => !isRunning && setExpanded(!expanded)}
        className={cn("w-full text-left group", isRunning && "cursor-default")}
      >
        <div className="flex items-baseline gap-2 py-0.5 min-w-0">
          <span className={cn(
            "text-xs font-mono truncate min-w-0 flex-1",
            failed ? "text-red-400"
              : (isActive || isRunning) ? "text-blue-400"
              : "text-foreground/80",
          )}>
            {label}{isRunning ? "…" : ""}
          </span>
          {entry.toolDurationMs != null && (
            <span className="text-[10px] text-muted-foreground/60 shrink-0">
              {formatDuration(entry.toolDurationMs)}
            </span>
          )}
          {failed && entry.toolIssue && (
            <span className="text-[10px] text-red-400 truncate max-w-[200px] shrink-0">
              {entry.toolIssue}
            </span>
          )}
        </div>
      </button>
      {expanded && !isRunning && <ToolDetail entry={entry} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ToolStepList — vertical list grouped by subagent boundaries
// ---------------------------------------------------------------------------

export function ToolStepList({ calls, isActive }: { calls: TranscriptEntry[]; isActive: boolean }) {
  const visibleCalls = calls.filter((c) => c.toolName !== "report_intent");
  const segments = groupToolCalls(visibleCalls);
  return (
    <div className="relative sm:ml-1">
      <div className="absolute left-[7px] top-2 bottom-2 w-px border-l border-dotted border-border/60" />
      <div className="space-y-0.5">
        {segments.map((seg, i) => {
          const isLastSeg = i === segments.length - 1;
          if (seg.type === "subagent-group") {
            return (
              <SubAgentSection
                key={seg.entry.seq}
                entry={seg.entry}
                childCalls={seg.children}
                isActive={isActive && isLastSeg}
              />
            );
          }
          return (
            <ToolStep
              key={seg.entry.seq}
              entry={seg.entry}
              isActive={isActive && isLastSeg}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// extractReportIntent
// ---------------------------------------------------------------------------

export function extractReportIntent(calls: TranscriptEntry[]): string | null {
  const intentCall = calls.find((c) => c.toolName === "report_intent");
  if (!intentCall?.toolArgs) return null;
  try {
    const args = JSON.parse(intentCall.toolArgs) as Record<string, unknown>;
    return typeof args.intent === "string" ? args.intent : null;
  } catch {
    return null;
  }
}
