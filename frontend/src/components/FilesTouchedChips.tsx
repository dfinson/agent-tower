import { Eye, FilePlus, Pencil } from "lucide-react";
import { useMemo, useState } from "react";
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
    return stepEntries.filter((e) => {
      if (e.role !== "tool_call" || !e.toolArgs) return false;
      try {
        const args = JSON.parse(e.toolArgs);
        const fp = args.filePath ?? args.file_path ?? args.path ?? "";
        return repoRelative(fp) === expandedFile;
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
              onClick={() => setExpandedFile(isExpanded ? null : path)}
              className={chipClass}
            >
              {kind === "create" ? <FilePlus size={10} /> : kind === "edit" ? <Pencil size={10} /> : <Eye size={10} />}
              {basename(path)}
              {editCount > 1 && <span className="text-[10px] opacity-60">×{editCount}</span>}
              {parentDir(repoPath) && <span className="text-[10px] opacity-60">{parentDir(repoPath)}/</span>}
            </button>
          );
        })}
      </div>

      {/* Expanded: show tool calls for the selected file */}
      {expandedFile && fileToolCalls.length > 0 && (
        <div className="mt-1.5 ml-2 border-l border-border pl-3 space-y-1">
          {fileToolCalls.map((tc) => {
            const name = tc.toolName?.split("/").pop() ?? tc.toolName ?? "";
            const display = tc.toolDisplay || name;
            return (
              <div key={tc.seq} className="text-xs text-muted-foreground">
                <span className={tc.toolSuccess === false ? "text-destructive" : "text-foreground/70"}>
                  {tc.toolSuccess === false ? "✗" : "✓"}
                </span>{" "}
                <span className="font-mono">{display}</span>
                {tc.toolDurationMs != null && (
                  <span className="ml-1 tabular-nums">
                    {tc.toolDurationMs < 1000 ? `${tc.toolDurationMs}ms` : `${(tc.toolDurationMs / 1000).toFixed(1)}s`}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
