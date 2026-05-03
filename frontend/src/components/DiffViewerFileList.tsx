import { useState, useCallback, useRef, useLayoutEffect } from "react";
import { type LucideIcon, FileCode, FilePlus, FileMinus, FileEdit, Check, Minus, Info, Eye, ArrowUpDown, BookOpenCheck, Lightbulb, Columns2 } from "lucide-react";
import { cn } from "../lib/utils";
import { Tooltip } from "./ui/tooltip";
import type { DiffFileModel, FileMotivation, HunkMotivation } from "../api/types";

const STATUS_ICON: Record<string, LucideIcon> = {
  added: FilePlus,
  deleted: FileMinus,
  modified: FileEdit,
  renamed: FileEdit,
};

const STATUS_BADGE: Record<string, string> = {
  added: "text-green-400 border-green-800",
  deleted: "text-red-400 border-red-800",
  modified: "text-blue-400 border-blue-800",
  renamed: "text-yellow-400 border-yellow-800",
};

export const STATUS_ICON_CLASS: Record<string, string> = {
  added: "text-green-400",
  deleted: "text-red-400",
  modified: "text-blue-400",
  renamed: "text-yellow-400",
};

export { STATUS_ICON, STATUS_BADGE };

/**
 * Displays a file path truncated from the left by path segment when it overflows.
 */
function TruncatedPath({ path }: { path: string }) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const [displayPath, setDisplayPath] = useState(path);

  const computeTruncation = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const segments = path.split("/");
    for (let start = 0; start < segments.length; start++) {
      const candidate =
        start === 0 ? path : "\u2026/" + segments.slice(start).join("/");
      el.textContent = candidate;
      if (el.scrollWidth <= el.offsetWidth + 1 || start === segments.length - 1) {
        setDisplayPath(candidate);
        return;
      }
    }
  }, [path]);

  useLayoutEffect(() => {
    computeTruncation();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(computeTruncation);
    ro.observe(el);
    return () => ro.disconnect();
  }, [computeTruncation]);

  return (
    <span
      ref={containerRef}
      className="text-xs flex-1 min-w-0 overflow-hidden whitespace-nowrap text-foreground"
      title={path}
    >
      {displayPath}
    </span>
  );
}

interface DiffViewerFileListProps {
  diffs: DiffFileModel[];
  selectedIdx: number;
  setSelectedIdx: (idx: number) => void;
  sidebarWidth: number;
  canAsk: boolean;
  sortByChurn: boolean;
  setSortByChurn: (v: boolean) => void;
  splitView: boolean;
  setSplitView: (v: boolean) => void;
  showIntent: boolean;
  setShowIntent: (v: boolean) => void;
  hunkMotivations: Record<string, HunkMotivation>;
  fileMotivations: Record<string, FileMotivation>;
  viewedFiles: Set<number>;
  contextFiles: { filePath: string; readCount: number }[];
  totalAdditions: number;
  totalDeletions: number;
  isFileFullyChecked: (fi: number) => boolean;
  isFilePartiallyChecked: (fi: number) => boolean;
  toggleFile: (fi: number) => void;
}

export function DiffViewerFileList({
  diffs,
  selectedIdx,
  setSelectedIdx,
  sidebarWidth,
  canAsk,
  sortByChurn,
  setSortByChurn,
  splitView,
  setSplitView,
  showIntent,
  setShowIntent,
  hunkMotivations,
  fileMotivations,
  viewedFiles,
  contextFiles,
  totalAdditions,
  totalDeletions,
  isFileFullyChecked,
  isFilePartiallyChecked,
  toggleFile,
}: DiffViewerFileListProps) {
  const [contextFilesOpen, setContextFilesOpen] = useState(false);

  return (
    <div
      className="hidden md:flex shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card"
      style={{ width: sidebarWidth }}
    >
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-muted-foreground">{diffs.length} files</span>
        <div className="flex items-center gap-2">
          {/* WS1: Sort by churn toggle */}
          {diffs.some((f) => (f.writeCount ?? 0) > 1) && (
            <Tooltip content={sortByChurn ? "Sort by file order" : "Sort by edit churn"}>
              <button
                onClick={() => setSortByChurn(!sortByChurn)}
                className={cn(
                  "p-0.5 rounded transition-colors",
                  sortByChurn ? "text-orange-400 hover:text-orange-300" : "text-muted-foreground/40 hover:text-muted-foreground",
                )}
              >
                <ArrowUpDown size={13} />
              </button>
            </Tooltip>
          )}
          {Object.keys(hunkMotivations).length > 0 && (
            <Tooltip content={showIntent ? "Hide intent annotations" : "Show intent annotations"}>
              <button
                onClick={() => setShowIntent(!showIntent)}
                className={cn(
                  "p-0.5 rounded transition-colors",
                  showIntent ? "text-amber-400 hover:text-amber-300" : "text-muted-foreground/40 hover:text-muted-foreground",
                )}
              >
                <Lightbulb size={13} />
              </button>
            </Tooltip>
          )}
          <Tooltip content={splitView ? "Unified diff" : "Split diff"}>
            <button
              onClick={() => setSplitView(!splitView)}
              className={cn(
                "p-0.5 rounded transition-colors",
                splitView ? "text-blue-400 hover:text-blue-300" : "text-muted-foreground/40 hover:text-muted-foreground",
              )}
            >
              <Columns2 size={13} />
            </button>
          </Tooltip>
          <span className="text-xs text-green-400">+{totalAdditions}</span>
          <span className="text-xs text-red-400">-{totalDeletions}</span>
          {contextFiles.length > 0 && (
            <span className="text-xs text-blue-400">· {contextFiles.length} read</span>
          )}
        </div>
      </div>
      {/* WS7: Review progress bar */}
      {diffs.length > 1 && (
        <div className="flex items-center gap-1.5 px-3 py-1 border-b border-border/50 bg-muted/10">
          <BookOpenCheck size={11} className="text-muted-foreground/60 shrink-0" />
          <span className="text-[10px] text-muted-foreground/70">{viewedFiles.size}/{diffs.length} reviewed</span>
          <div className="flex-1 h-1 rounded-full bg-muted/30 overflow-hidden">
            <div
              className="h-full bg-primary/60 rounded-full transition-all duration-300"
              style={{ width: `${Math.round((viewedFiles.size / diffs.length) * 100)}%` }}
            />
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto">
        {diffs.map((file, i) => {
          const Icon = STATUS_ICON[file.status] ?? FileCode;
          const fileChecked = isFileFullyChecked(i);
          const filePartial = isFilePartiallyChecked(i);
          const fileMot = fileMotivations[file.path];
          const churn = file.writeCount ?? 0;
          return (
            <div key={i} className="flex flex-col">
              <div
                className={cn(
                  "flex items-center gap-1.5 px-2 py-2 text-sm transition-colors w-full",
                  i === selectedIdx ? "bg-accent" : "hover:bg-accent/50",
                )}
              >
                {/* File checkbox — tri-state */}
                {canAsk ? (
                  <Tooltip content="Select to ask about this file's changes">
                    <button
                      type="button"
                      onClick={() => toggleFile(i)}
                      className={cn(
                        "shrink-0 w-5 h-5 md:w-4 md:h-4 rounded-[3px] border-2 flex items-center justify-center transition-colors cursor-pointer",
                        fileChecked || filePartial
                          ? "bg-primary border-primary text-primary-foreground"
                          : "border-muted-foreground/60 hover:border-foreground/80",
                      )}
                    >
                      {fileChecked && <Check size={12} strokeWidth={3} />}
                      {filePartial && <Minus size={12} strokeWidth={3} />}
                    </button>
                  </Tooltip>
                ) : (
                  <span className="shrink-0 w-5 md:w-4" />
                )}
                <button
                  type="button"
                  onClick={() => setSelectedIdx(i)}
                  className="flex items-center gap-2 flex-1 min-w-0 text-left"
                >
                  <Icon size={14} className={cn("shrink-0", STATUS_ICON_CLASS[file.status])} />
                  {fileMot && (
                    <Tooltip
                      content={
                        <div className="max-w-[280px]">
                          <p className="font-medium text-foreground">{fileMot.title}</p>
                          {fileMot.why && (
                            <p className="mt-0.5 text-muted-foreground">{fileMot.why}</p>
                          )}
                          {(fileMot.unmatchedEdits?.length ?? 0) > 0 && (
                            <div className="mt-1.5 pt-1.5 border-t border-border">
                              <p className="text-[10px] text-muted-foreground/60 mb-1">Other edits:</p>
                              {fileMot.unmatchedEdits.map((e, ei) => (
                                <p key={ei} className="text-muted-foreground">{e.title}</p>
                              ))}
                            </div>
                          )}
                        </div>
                      }
                      side="right"
                    >
                      <Info size={11} className="shrink-0 text-amber-400/70" />
                    </Tooltip>
                  )}
                  <TruncatedPath path={file.path} />
                  {/* WS1: Churn badge */}
                  {churn >= 2 && (
                    <Tooltip content={`Edited ${churn} times${file.retryCount ? ` (${file.retryCount} retries)` : ""} — high churn may indicate the agent struggled with this file`}>
                      <span className={cn(
                        "text-[9px] font-bold rounded px-1 shrink-0",
                        churn >= 4 ? "bg-red-500/20 text-red-400" : "bg-amber-500/20 text-amber-400",
                      )}>
                        {churn}×
                      </span>
                    </Tooltip>
                  )}
                  <span className={cn("text-xs border rounded px-1 hidden md:inline", STATUS_BADGE[file.status])}>
                    +{file.additions} -{file.deletions}
                  </span>
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* WS2: Context files read but not modified */}
      {contextFiles.length > 0 && (
        <div className="border-t border-border">
          <button
            type="button"
            onClick={() => setContextFilesOpen(!contextFilesOpen)}
            className="flex items-center gap-1.5 w-full px-3 py-1.5 text-left hover:bg-accent/30 transition-colors"
          >
            <Eye size={11} className="text-blue-400/70 shrink-0" />
            <span className="text-[10px] text-muted-foreground">Context files read ({contextFiles.length})</span>
          </button>
          {contextFilesOpen && (
            <div className="max-h-32 overflow-y-auto">
              {contextFiles.map((cf, ci) => (
                <div key={ci} className="flex items-center gap-2 px-3 py-1 text-[10px] text-muted-foreground/70">
                  <FileCode size={10} className="shrink-0 text-blue-400/40" />
                  <span className="flex-1 min-w-0 truncate" title={cf.filePath}>
                    {cf.filePath}
                  </span>
                  <span className="text-blue-400/50 shrink-0">{cf.readCount}×</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
