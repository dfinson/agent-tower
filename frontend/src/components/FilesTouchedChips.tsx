import { Eye, FilePlus, Pencil } from "lucide-react";
import { useMemo, useState, Fragment } from "react";
import { cn } from "../lib/utils";
import type { Step } from "../store";
import { useStore, selectStepEntries } from "../store";

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
  "read_file", "view_image", "Read", "View",
]);

interface FileInfo {
  path: string;
  repoPath: string;
  kind: "create" | "edit" | "read";
  editCount: number;
}

/** Render a unified diff of old → new with removed/added/context lines. */
function DiffBlock({ oldStr, newStr, success }: { oldStr: string; newStr: string; success?: boolean }) {
  const lines = useMemo(() => {
    const oldLines = oldStr.split("\n");
    const newLines = newStr.split("\n");
    const result: { type: "ctx" | "del" | "add"; text: string }[] = [];

    const lcs = buildLCS(oldLines, newLines);
    let oi = 0, ni = 0, li = 0;
    while (oi < oldLines.length || ni < newLines.length) {
      if (li < lcs.length && oi < oldLines.length && ni < newLines.length && oldLines[oi] === lcs[li] && newLines[ni] === lcs[li]) {
        result.push({ type: "ctx", text: oldLines[oi]! });
        oi++; ni++; li++;
      } else if (oi < oldLines.length && (li >= lcs.length || oldLines[oi] !== lcs[li])) {
        result.push({ type: "del", text: oldLines[oi]! });
        oi++;
      } else if (ni < newLines.length && (li >= lcs.length || newLines[ni] !== lcs[li])) {
        result.push({ type: "add", text: newLines[ni]! });
        ni++;
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
              <span className="select-none opacity-50 mr-2">-</span>{line.text}
            </div>
          );
          if (line.type === "add") return (
            <div key={i} className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <span className="select-none opacity-50 mr-2">+</span>{line.text}
            </div>
          );
          return (
            <div key={i} className="text-muted-foreground">
              <span className="select-none opacity-30 mr-2"> </span>{line.text}
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

export function FilesTouchedChips({ step }: { step: Step }) {
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
    // Combine written + read, deduped (written takes priority)
    const allFiles = new Set([...writtenFiles, ...readFiles]);

    const infos: FileInfo[] = [...allFiles].map((f) => ({
      path: f,
      repoPath: f,
      kind: created.has(f) ? "create" as const : editCounts.has(f) ? "edit" as const : "read" as const,
      editCount: editCounts.get(f) ?? 0,
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

  return (
    <div className="mt-1.5">
      <div className="flex flex-wrap gap-1">
        {fileInfos.map(({ path, repoPath, kind, editCount }) => {
          const isExpanded = expandedFile === path;
          const chipClass = kind === "create"
            ? "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors"
            : kind === "edit"
              ? "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 transition-colors"
              : "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground hover:bg-muted/80 transition-colors";
          return (
            <button
              key={path}
              type="button"
              title={repoPath}
              onClick={(e) => { e.stopPropagation(); setExpandedFile(isExpanded ? null : path); }}
              className={cn(
                chipClass,
                isExpanded && "ring-1 ring-foreground/30",
              )}
            >
              {kind === "create" ? <FilePlus size={10} /> : kind === "edit" ? <Pencil size={10} /> : <Eye size={10} />}
              {basename(path)}
              {editCount > 1 && <span className="text-[10px] opacity-60">×{editCount}</span>}
              {parentDir(repoPath) && <span className="text-[10px] opacity-60">{parentDir(repoPath)}/</span>}
            </button>
          );
        })}
      </div>

      {/* Expanded: show diffs for the selected file */}
      {expandedFile && fileToolCalls.length > 0 && (
        <div className="mt-1.5 ml-2 border-l border-border pl-3 space-y-2">
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
              return (
                <div key={tc.seq} className="rounded bg-muted/30 overflow-hidden">
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

            if (oldStr || newStr) {
              return <DiffBlock key={tc.seq} oldStr={oldStr} newStr={newStr} success={tc.toolSuccess} />;
            }

            // Fallback: read or unknown tool — show display label
            const display = tc.toolDisplay || name;
            return (
              <div key={tc.seq} className="text-xs text-muted-foreground font-mono">
                {tc.toolSuccess === false ? "✗" : "✓"} {display}
              </div>
            );
          })}
        </div>
      )}
      {expandedFile && fileToolCalls.length === 0 && (
        <div className="mt-1.5 ml-2 text-xs text-muted-foreground italic">
          No tool data available for this file
        </div>
      )}
    </div>
  );
}
