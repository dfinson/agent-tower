/**
 * InlineDiffBlock — compact collapsible diff embedded in the story narrative.
 *
 * Shows a filename header with +/- counts and a collapsed-by-default diff.
 * Context lines beyond 2 per hunk side are hidden behind an expandable
 * "show more" control.
 */

import { useState, useMemo } from "react";
import { ChevronRight, FileCode } from "lucide-react";
import type { DiffFileModel, DiffLineModel } from "../api/types";
import { cn } from "../lib/utils";

/** How many context lines to show above/below each change by default. */
const DEFAULT_CONTEXT = 2;

interface InlineDiffBlockProps {
  file: DiffFileModel;
  /** Clicking the filename header navigates to this file in the full diff viewer. */
  onNavigate?: () => void;
}

/** Trim context lines in a hunk down to `ctx` lines around each change span. */
function trimContext(lines: DiffLineModel[], ctx: number): { visible: DiffLineModel[]; trimmed: boolean } {
  if (lines.length === 0) return { visible: [], trimmed: false };

  // Mark which lines are changes (additions/deletions)
  const isChange = lines.map((l) => l.type !== "context");

  // For each line, compute distance to nearest change
  const dist = new Array(lines.length).fill(Infinity);
  // Forward pass
  let last = -Infinity;
  for (let i = 0; i < lines.length; i++) {
    if (isChange[i]) last = i;
    if (last >= 0) dist[i] = Math.min(dist[i], i - last);
  }
  // Backward pass
  last = Infinity;
  for (let i = lines.length - 1; i >= 0; i--) {
    if (isChange[i]) last = i;
    if (last < Infinity) dist[i] = Math.min(dist[i], last - i);
  }

  const visible: DiffLineModel[] = [];
  let trimmed = false;
  let skipping = false;

  for (let i = 0; i < lines.length; i++) {
    if (isChange[i] || dist[i] <= ctx) {
      if (skipping) {
        // Insert a separator for the skipped region
        visible.push({ type: "context", content: "···" });
        skipping = false;
      }
      visible.push(lines[i]!);
    } else {
      trimmed = true;
      skipping = true;
    }
  }
  return { visible, trimmed };
}

const lineColors: Record<string, string> = {
  addition: "bg-emerald-500/10 text-emerald-300",
  deletion: "bg-red-500/10 text-red-300",
  context: "text-muted-foreground/70",
};

const linePrefix: Record<string, string> = {
  addition: "+",
  deletion: "-",
  context: " ",
};

export function InlineDiffBlock({ file, onNavigate }: InlineDiffBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const fileName = file.path.split("/").pop() ?? file.path;
  const dir = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/") + 1) : "";

  const allLines = useMemo(
    () => file.hunks.flatMap((h) => h.lines),
    [file.hunks],
  );

  const { visible: trimmedLines, trimmed: hasTrimmed } = useMemo(
    () => trimContext(allLines, DEFAULT_CONTEXT),
    [allLines],
  );

  const displayLines = expanded ? allLines : trimmedLines;

  if (allLines.length === 0) {
    // No diff data — fall back to a simple filename link
    return (
      <button
        type="button"
        onClick={onNavigate}
        className="inline text-primary hover:text-primary/80 font-mono text-[11px] underline underline-offset-2 decoration-primary/40 hover:decoration-primary transition-colors mx-0.5"
        title={file.path}
      >
        {fileName}
      </button>
    );
  }

  return (
    <div className="my-2 rounded-md border border-border/50 bg-background/50 overflow-hidden text-[11px]">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 bg-muted/30 border-b border-border/30">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronRight
            size={11}
            className={cn("transition-transform", expanded && "rotate-90")}
          />
        </button>
        <FileCode size={11} className="text-muted-foreground/60 shrink-0" />
        <button
          type="button"
          onClick={onNavigate}
          className="font-mono text-primary hover:text-primary/80 truncate transition-colors text-left"
          title={file.path}
        >
          {dir && <span className="text-muted-foreground/50">{dir}</span>}
          {fileName}
        </button>
        <span className="ml-auto flex items-center gap-1.5 text-[10px] shrink-0">
          {file.additions > 0 && <span className="text-emerald-400">+{file.additions}</span>}
          {file.deletions > 0 && <span className="text-red-400">-{file.deletions}</span>}
        </span>
      </div>

      {/* Diff lines */}
      <div className="overflow-x-auto">
        <pre className="px-0 py-0.5 leading-[1.6]">
          {displayLines.map((line, i) => (
            <div
              key={i}
              className={cn(
                "px-2 font-mono whitespace-pre",
                lineColors[line.type],
                line.content === "···" && "text-center text-muted-foreground/40 py-0.5",
              )}
            >
              {line.content === "···" ? (
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="hover:text-muted-foreground transition-colors"
                >
                  ···
                </button>
              ) : (
                <>
                  <span className="select-none opacity-50 mr-1">{linePrefix[line.type]}</span>
                  {line.content}
                </>
              )}
            </div>
          ))}
        </pre>
      </div>

      {/* Expand/collapse control */}
      {hasTrimmed && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="w-full px-2 py-0.5 text-[10px] text-muted-foreground/50 hover:text-muted-foreground bg-muted/20 border-t border-border/30 transition-colors text-center"
        >
          {expanded
            ? "Show less"
            : `Show all ${allLines.length} lines`}
        </button>
      )}
    </div>
  );
}
