import { Eye, FilePlus, Pencil } from "lucide-react";
import { useMemo, useState, Fragment } from "react";
import { cn } from "../lib/utils";
import type { Step } from "../store";
import { useStore, selectStepEntries } from "../store";
import { AgentMarkdown } from "./AgentMarkdown";

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

function parentDir(path: string): string {
  const parts = path.split("/");
  if (parts.length <= 1) return "";
  return parts[parts.length - 2] ?? "";
}

/**
 * Strip worktree prefix from absolute paths.
 * Handles both /.codeplane-worktrees/ paths and other absolute paths.
 * If the path is already relative, returns as-is.
 */
function repoRelative(path: string): string {
  const marker = "/.codeplane-worktrees/";
  const idx = path.indexOf(marker);
  if (idx !== -1) {
    // Skip worktree name: …/.codeplane-worktrees/<name>/rest
    const afterMarker = path.slice(idx + marker.length);
    const slashIdx = afterMarker.indexOf("/");
    return slashIdx >= 0 ? afterMarker.slice(slashIdx + 1) : afterMarker;
  }
  // Already relative
  if (!path.startsWith("/")) return path;
  // Unknown absolute — show last 2 parts
  const parts = path.split("/");
  return parts.length <= 2 ? path : parts.slice(-2).join("/");
}

/** Tools that create new files. */
const CREATE_TOOLS = new Set(["create_file", "Write", "write", "write_file", "create", "create_or_update_file"]);
/** Tools that edit existing files. */
const EDIT_TOOLS = new Set([
  "replace_string_in_file", "multi_replace_string_in_file", "edit", "Edit",
  "str_replace_based_edit_tool", "str_replace_editor", "insert_edit_into_file",
  "edit_file", "write_file",
]);
/** Tools that read files (shown as view-only chips). */
const READ_TOOLS = new Set([
  "read_file", "view_image", "Read", "View", "view", "read_files", "list_files",
]);

interface FileInfo {
  path: string;
  repoPath: string;
  kind: "create" | "edit" | "read";
  editCount: number;
  hasToolData: boolean;
}

function isMdFile(path: string): boolean {
  return /\.md$/i.test(path);
}

/** Render a unified diff of old → new with removed/added/context lines. */
function DiffBlock({ oldStr, newStr, success }: { oldStr: string; newStr: string; success?: boolean }) {
  const lines = useMemo(() => {
    const oldLines = oldStr.split("\n");
    const newLines = newStr.split("\n");
    const result: { type: "ctx" | "del" | "add"; text: string; lineNo: number }[] = [];

    const lcs = buildLCS(oldLines, newLines);
    let oi = 0, ni = 0, li = 0;
    let oldLineNo = 1, newLineNo = 1;
    while (oi < oldLines.length || ni < newLines.length) {
      if (li < lcs.length && oi < oldLines.length && ni < newLines.length && oldLines[oi] === lcs[li] && newLines[ni] === lcs[li]) {
        result.push({ type: "ctx", text: oldLines[oi]!, lineNo: newLineNo });
        oi++; ni++; li++; oldLineNo++; newLineNo++;
      } else if (oi < oldLines.length && (li >= lcs.length || oldLines[oi] !== lcs[li])) {
        result.push({ type: "del", text: oldLines[oi]!, lineNo: oldLineNo });
        oi++; oldLineNo++;
      } else if (ni < newLines.length && (li >= lcs.length || newLines[ni] !== lcs[li])) {
        result.push({ type: "add", text: newLines[ni]!, lineNo: newLineNo });
        ni++; newLineNo++;
      } else {
        break;
      }
    }
    return result;
  }, [oldStr, newStr]);

  return (
    <div className={`rounded overflow-hidden border ${success === false ? "border-destructive/30" : "border-border"}`}>
      <pre className="text-xs p-2 max-h-64 overflow-auto whitespace-pre-wrap break-all leading-relaxed">
        {lines.map((line, i) => {
          if (line.type === "del") return (
            <div key={i} className="bg-red-500/10 text-red-600 dark:text-red-400">
              <span className="inline-block w-8 text-right pr-2 select-none opacity-40 tabular-nums">{line.lineNo}</span>
              <span className="select-none opacity-50">-</span> {line.text}
            </div>
          );
          if (line.type === "add") return (
            <div key={i} className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <span className="inline-block w-8 text-right pr-2 select-none opacity-40 tabular-nums">{line.lineNo}</span>
              <span className="select-none opacity-50">+</span> {line.text}
            </div>
          );
          return (
            <div key={i} className="text-muted-foreground">
              <span className="inline-block w-8 text-right pr-2 select-none opacity-30 tabular-nums">{line.lineNo}</span>
              <span className="select-none opacity-30"> </span> {line.text}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

/** Build longest common subsequence of two string arrays. */
function buildLCS(a: string[], b: string[]): string[] {
  const m = a.length, n = b.length;
  if (m > 200 || n > 200) return [];
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array<number>(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i]![j] = a[i - 1] === b[j - 1] ? dp[i - 1]![j - 1]! + 1 : Math.max(dp[i - 1]![j]!, dp[i]![j - 1]!);
  const result: string[] = [];
  let i = m, j = n;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) { result.push(a[i - 1]!); i--; j--; }
    else if (dp[i - 1]![j]! >= dp[i]![j - 1]!) i--;
    else j--;
  }
  return result.reverse();
}

export function FilesTouchedChips({ step, collapsed, onExpand }: { step: Step; collapsed?: boolean; onExpand?: () => void }) {
  const stepEntries = useStore(selectStepEntries(step.jobId, step.stepId));
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  const fileInfos = useMemo(() => {
    const created = new Set<string>();
    const editCounts = new Map<string, number>();
    const readFiles = new Set<string>();

    for (const e of stepEntries) {
      if (e.role !== "tool_call" || !e.toolName) continue;
      const name = e.toolName.split("/").pop() ?? e.toolName;
      if (!e.toolArgs) continue;
      let fp = "";
      try {
        const args = JSON.parse(e.toolArgs);
        fp = args.filePath ?? args.file_path ?? args.path ?? "";
      } catch { continue; }
      if (!fp) continue;
      const rel = repoRelative(fp);

      if (CREATE_TOOLS.has(name)) created.add(rel);
      if (EDIT_TOOLS.has(name)) {
        editCounts.set(rel, (editCounts.get(rel) ?? 0) + 1);
      }
      if (READ_TOOLS.has(name)) readFiles.add(rel);
    }

    const writtenFiles = new Set((step.filesWritten ?? []).map(repoRelative));
    // Track which files have actual tool_call entries with parseable args
    const filesWithToolData = new Set([...created, ...editCounts.keys(), ...readFiles]);
    // Combine written + read, deduped (written takes priority)
    const allFiles = new Set([...writtenFiles, ...readFiles]);

    const infos: FileInfo[] = [...allFiles].map((f) => ({
      path: f,
      repoPath: f,
      kind: created.has(f) ? "create" as const : editCounts.has(f) ? "edit" as const : "read" as const,
      editCount: editCounts.get(f) ?? 0,
      hasToolData: filesWithToolData.has(f),
    }));
    // Sort: creates first, then edits, then reads
    const kindOrder = { create: 0, edit: 1, read: 2 };
    infos.sort((a, b) => kindOrder[a.kind] - kindOrder[b.kind]);
    return infos;
  }, [stepEntries, step.filesWritten]);

  // Tool calls that touched the expanded file
  const fileToolCalls = useMemo(() => {
    if (!expandedFile) return [];
    const target = expandedFile;
    const targetBase = basename(target);
    return stepEntries.filter((e) => {
      if (e.role !== "tool_call" || !e.toolArgs) return false;
      try {
        const args = JSON.parse(e.toolArgs);
        const fp = args.filePath ?? args.file_path ?? args.path ?? "";
        if (!fp) return false;
        const rel = repoRelative(fp);
        // Exact match first, then endsWith fallback for path prefix mismatches
        return rel === target || rel.endsWith("/" + target) || target.endsWith("/" + rel) || basename(rel) === targetBase;
      } catch { return false; }
    });
  }, [stepEntries, expandedFile]);

  if (!fileInfos.length) return null;

  // Collapsed mode: show compact summary instead of individual chips
  if (collapsed) {
    const createCount = fileInfos.filter((f) => f.kind === "create").length;
    const editCount = fileInfos.filter((f) => f.kind === "edit").length;
    const readCount = fileInfos.filter((f) => f.kind === "read").length;
    const parts: string[] = [];
    if (createCount > 0) parts.push(`${createCount} created`);
    if (editCount > 0) parts.push(`${editCount} edited`);
    if (readCount > 0) parts.push(`${readCount} read`);
    return (
      <div className="mt-1.5">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onExpand?.(); }}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {parts.join(", ")}
        </button>
      </div>
    );
  }

  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap gap-1">
        {fileInfos.map(({ path, repoPath, kind, editCount, hasToolData }) => {
          const isExpanded = expandedFile === path;
          const canExpand = hasToolData;
          const kindLabel = kind === "create" ? "Created" : kind === "edit" ? "Edited" : "Read";
          const chipClass = kind === "create"
            ? "inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors min-h-[32px]"
            : kind === "edit"
              ? "inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 transition-colors min-h-[32px]"
              : "inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-violet-500/10 text-violet-600 hover:bg-violet-500/20 transition-colors min-h-[32px]";
          return (
            <button
              key={path}
              type="button"
              aria-expanded={canExpand ? isExpanded : undefined}
              aria-label={`${kindLabel}: ${repoPath}${editCount > 1 ? `, ${editCount} edits` : ""}`}
              title={repoPath}
              onClick={(e) => { e.stopPropagation(); if (canExpand) setExpandedFile(isExpanded ? null : path); }}
              className={cn(
                chipClass,
                canExpand && isExpanded && "ring-1 ring-foreground/30",
                !canExpand && "cursor-default",
              )}
            >
              {kind === "create" ? <FilePlus size={12} aria-hidden="true" /> : kind === "edit" ? <Pencil size={12} aria-hidden="true" /> : <Eye size={12} aria-hidden="true" />}
              <span className="sr-only">{kindLabel}:</span>
              {basename(path)}
              {editCount > 1 && <span className="text-[10px] opacity-60">×{editCount}</span>}
              {parentDir(repoPath) && <span className="text-[10px] opacity-60">{parentDir(repoPath)}/</span>}
            </button>
          );
        })}
      </div>

      {/* Expanded: show diffs for the selected file */}
      {expandedFile && fileToolCalls.length > 0 && (
        <div className="mt-1.5 ml-2 border-l border-border pl-3 space-y-2" role="region" aria-label={`Changes to ${basename(expandedFile)}`}>
          {fileToolCalls.map((tc) => {
            const name = tc.toolName?.split("/").pop() ?? tc.toolName ?? "";
            let oldStr = "";
            let newStr = "";
            let content = "";
            let isCreate = false;
            try {
              const args = JSON.parse(tc.toolArgs ?? "{}");
              oldStr = args.oldString ?? args.old_str ?? args.oldStr ?? "";
              newStr = args.newString ?? args.new_str ?? args.newStr ?? "";
              content = args.content ?? args.file_text ?? "";
              if (CREATE_TOOLS.has(name) && content) isCreate = true;
              // multi_replace_string_in_file has replacements array
              if (args.replacements && Array.isArray(args.replacements)) {
                return (
                  <Fragment key={tc.seq}>
                    {args.replacements.map((r: { oldString?: string; newString?: string }, ri: number) => (
                      <DiffBlock key={ri} oldStr={r.oldString ?? ""} newStr={r.newString ?? ""} success={tc.toolSuccess} />
                    ))}
                  </Fragment>
                );
              }
            } catch { /* ignore parse errors */ }

            if (isCreate && content) {
              return <CreatedFileBlock key={tc.seq} path={expandedFile!} content={content} />;
            }

            if (oldStr || newStr) {
              return <DiffBlock key={tc.seq} oldStr={oldStr} newStr={newStr} success={tc.toolSuccess} />;
            }

            // Read tool — show actual file content from tool result
            if (READ_TOOLS.has(name) && tc.toolResult) {
              const resultText = tc.toolResult;
              const display = tc.toolDisplay || tc.toolDisplayFull || name;
              const filePath = expandedFile ?? "";
              return <ReadContentBlock key={tc.seq} header={display} content={resultText} filePath={filePath} />;
            }

            // Fallback: unknown tool — show display label
            const display = tc.toolDisplay || name;
            return (
              <div key={tc.seq} className="text-xs text-muted-foreground font-mono">
                {tc.toolSuccess === false ? "✗" : "✓"} {display}
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}

/** Segmented toggle for Rendered / Source views on markdown content. */
function MdViewToggle({ raw, onToggle }: { raw: boolean; onToggle: () => void }) {
  return (
    <div className="inline-flex rounded border border-border text-[11px] leading-none overflow-hidden" role="radiogroup" aria-label="View mode">
      <button
        type="button"
        role="radio"
        aria-checked={!raw}
        onClick={(e) => { e.stopPropagation(); if (raw) onToggle(); }}
        className={cn(
          "px-2 py-1 transition-colors",
          !raw ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground",
        )}
      >
        Rendered
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={raw}
        onClick={(e) => { e.stopPropagation(); if (!raw) onToggle(); }}
        className={cn(
          "px-2 py-1 transition-colors border-l border-border",
          raw ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground",
        )}
      >
        Source
      </button>
    </div>
  );
}

/** Block for newly created file content — renders .md files as markdown by default. */
function CreatedFileBlock({ path, content }: { path: string; content: string }) {
  const mdFile = isMdFile(path);
  const [raw, setRaw] = useState(!mdFile);

  if (!mdFile || raw) {
    return (
      <div className="rounded bg-muted/30 overflow-hidden">
        {mdFile && (
          <div className="flex items-center justify-end px-2 py-1 border-b border-border/50">
            <MdViewToggle raw={raw} onToggle={() => setRaw((v) => !v)} />
          </div>
        )}
        <pre className="text-xs p-2 max-h-48 overflow-auto whitespace-pre-wrap break-all">
          {content.split("\n").map((line, i) => (
            <div key={i} className="text-emerald-600 dark:text-emerald-400">
              <span className="select-none text-emerald-600/50 mr-2">+</span>{line}
            </div>
          ))}
        </pre>
      </div>
    );
  }

  return (
    <div className="rounded overflow-hidden border border-border">
      <div className="flex items-center justify-end px-2 py-1 bg-muted/40 border-b border-border/50">
        <MdViewToggle raw={raw} onToggle={() => setRaw((v) => !v)} />
      </div>
      <div className="text-sm p-3 max-h-72 overflow-auto leading-relaxed text-foreground/90 prose prose-sm dark:prose-invert max-w-none">
        <AgentMarkdown content={content} />
      </div>
    </div>
  );
}

function ReadContentBlock({ header, content, filePath }: { header: string; content: string; filePath?: string }) {
  const mdFile = filePath ? isMdFile(filePath) : false;
  const [raw, setRaw] = useState(!mdFile);
  const lineCount = content.split("\n").length;

  return (
    <div className="rounded overflow-hidden border border-border">
      <div className="flex items-center justify-between px-2 py-1 bg-muted/40 text-xs text-muted-foreground border-b border-border">
        <span className="font-mono truncate">{header}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className="tabular-nums">{lineCount} lines</span>
          {mdFile && <MdViewToggle raw={raw} onToggle={() => setRaw((v) => !v)} />}
        </div>
      </div>
      {!raw ? (
        <div className="text-sm p-3 max-h-72 overflow-auto leading-relaxed text-foreground/90 prose prose-sm dark:prose-invert max-w-none">
          <AgentMarkdown content={content} />
        </div>
      ) : (
        <pre className="text-xs p-2 max-h-64 overflow-auto whitespace-pre-wrap break-all leading-relaxed text-foreground/80">
          {content}
        </pre>
      )}
    </div>
  );
}
