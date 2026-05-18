/**
 * CoveragePopover — floating popover shown when clicking a green coverage dot.
 * Lists covering tests with pass/fail/notrun status and Peek/↗ actions.
 */

import { useEffect, useRef } from "react";
import type { CoveragePopoverState } from "../hooks/useCoverageLayers";
import { cn } from "../lib/utils";

interface CoveragePopoverProps {
  state: CoveragePopoverState;
  onDismiss: () => void;
  onPeek?: (file: string, line: number) => void;
  onGoto?: (file: string, line: number) => void;
}

const STATUS_ICON: Record<string, string> = {
  pass: "✓",
  fail: "✗",
  notrun: "○",
};

const STATUS_CLASS: Record<string, string> = {
  pass: "text-green-400",
  fail: "text-red-400",
  notrun: "text-zinc-500",
};

const STATUS_TITLE: Record<string, string> = {
  pass: "Passed",
  fail: "Failed",
  notrun: "Not run",
};

export function CoveragePopover({ state, onDismiss, onPeek, onGoto }: CoveragePopoverProps) {
  const ref = useRef<HTMLDivElement>(null);

  // Close on Escape or outside click
  useEffect(() => {
    if (!state.visible) return;

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onDismiss();
      }
    };

    document.addEventListener("keydown", handleKey);
    document.addEventListener("mousedown", handleClick, true);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("mousedown", handleClick, true);
    };
  }, [state.visible, onDismiss]);

  if (!state.visible || state.tests.length === 0) return null;

  return (
    <div
      ref={ref}
      className="fixed z-[100] min-w-[240px] max-w-[360px] rounded-md border border-border bg-popover shadow-lg animate-in fade-in-0 zoom-in-95 duration-100"
      style={{ top: state.top, left: state.left }}
    >
      <div className="px-3 py-1.5 border-b border-border">
        <span className="text-xs font-medium text-muted-foreground">
          Covering tests:
        </span>
      </div>
      <div className="max-h-[200px] overflow-y-auto py-1">
        {state.tests.map((test, i) => {
          const parts = test.file.split(":");
          const fileName = parts[0] || test.file;
          const lineNum = parseInt(parts[1] || "1", 10);

          return (
            <div
              key={i}
              className="flex items-center gap-2 px-3 py-1 hover:bg-accent/50 transition-colors"
            >
              <span
                className={cn("text-xs font-mono shrink-0", STATUS_CLASS[test.status])}
                title={STATUS_TITLE[test.status]}
              >
                {STATUS_ICON[test.status]}
              </span>
              <div className="flex-1 min-w-0">
                <span className={cn(
                  "text-xs font-mono block truncate",
                  test.status === "fail" && "text-red-400",
                )}>
                  {test.name}
                </span>
                <span className="text-[10px] text-muted-foreground truncate block">
                  {test.file}
                </span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {onPeek && (
                  <button
                    className="text-[10px] text-muted-foreground hover:text-foreground px-1 py-0.5 rounded hover:bg-accent transition-colors"
                    onClick={() => onPeek(fileName, lineNum)}
                  >
                    Peek
                  </button>
                )}
                {onGoto && (
                  <button
                    className="text-[10px] text-muted-foreground hover:text-foreground px-1 py-0.5 rounded hover:bg-accent transition-colors"
                    title="Open in editor"
                    onClick={() => onGoto(fileName, lineNum)}
                  >
                    ↗
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
