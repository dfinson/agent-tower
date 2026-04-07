import { Code, Terminal } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "../lib/utils";
import type { Step } from "../store";
import { useStore, selectStepEntries } from "../store";
import { AgentMarkdown } from "./AgentMarkdown";

const TERMINAL_TOOLS = new Set(["bash", "run_in_terminal", "Bash"]);

export function CommandChips({ step, collapsed, onExpand }: { step: Step; collapsed?: boolean; onExpand?: () => void }) {
  const stepEntries = useStore(selectStepEntries(step.jobId, step.stepId));
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);

  const commands = useMemo(() => {
    return stepEntries.filter((e) => {
      if (e.role !== "tool_call" || !e.toolName) return false;
      if (e.toolVisibility !== "collapsed") return false;
      const name = e.toolName.split("/").pop() ?? e.toolName;
      return TERMINAL_TOOLS.has(name);
    });
  }, [stepEntries]);

  if (!commands.length) return null;

  // Collapsed mode: show compact summary
  if (collapsed) {
    return (
      <div className="mt-1">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onExpand?.(); }}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {commands.length} command{commands.length !== 1 ? "s" : ""}
        </button>
      </div>
    );
  }

  const expandedCmd = expandedSeq != null ? commands.find((c) => c.seq === expandedSeq) : null;

  return (
    <div className="mt-1">
      <div className="flex flex-wrap gap-1">
        {commands.map((tc) => {
          const isExpanded = expandedSeq === tc.seq;
          const chipLabel = (tc.toolDisplay ?? tc.toolName ?? "").split(" → ")[0];
          return (
            <button
              key={tc.seq}
              type="button"
              aria-expanded={isExpanded}
              aria-label={`Terminal: ${tc.toolDisplayFull ?? tc.toolDisplay ?? tc.toolName ?? ""}`}
              onClick={(e) => { e.stopPropagation(); setExpandedSeq(isExpanded ? null : tc.seq); }}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors min-h-[32px]",
                isExpanded && "ring-1 ring-foreground/30",
              )}
            >
              <Terminal size={12} aria-hidden="true" />
              <span className="sr-only">Terminal:</span>
              <span className="font-mono truncate max-w-[250px]">{chipLabel}</span>
            </button>
          );
        })}
      </div>

      {expandedCmd?.toolResult && (
        <ExpandedContent
          header={expandedCmd.toolDisplayFull ?? expandedCmd.toolDisplay ?? expandedCmd.toolName ?? ""}
          content={expandedCmd.toolResult}
        />
      )}
    </div>
  );
}

function ExpandedContent({ header, content }: { header: string; content: string }) {
  const mdFile = /\.md$/i.test(header);
  const [raw, setRaw] = useState(!mdFile);
  const lineCount = content.split("\n").length;

  return (
    <div className="mt-1.5 ml-2 border-l border-border pl-3" role="region" aria-label={`Output: ${header}`}>
      <div className="rounded overflow-hidden border border-border">
        <div className="flex items-center justify-between px-2 py-1 bg-muted/40 text-xs text-muted-foreground border-b border-border">
          <span className="font-mono truncate">{header}</span>
          <div className="flex items-center gap-2 shrink-0">
            <span className="tabular-nums">{lineCount} lines</span>
            {mdFile && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setRaw((v) => !v); }}
                className={cn(
                  "p-0.5 rounded hover:bg-muted transition-colors",
                  !raw ? "text-foreground" : "text-muted-foreground",
                )}
                aria-label={raw ? "Render markdown" : "View raw"}
                aria-pressed={!raw}
              >
                <Code size={12} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
        {!raw ? (
          <div className="text-xs p-2 max-h-64 overflow-auto leading-relaxed text-foreground/80 prose prose-xs dark:prose-invert max-w-none">
            <AgentMarkdown content={content} />
          </div>
        ) : (
          <pre className="text-xs p-2 max-h-64 overflow-auto whitespace-pre-wrap break-all leading-relaxed text-foreground/80">
            {content}
          </pre>
        )}
      </div>
    </div>
  );
}
