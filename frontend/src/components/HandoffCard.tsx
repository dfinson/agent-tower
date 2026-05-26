/**
 * HandoffCard — displays context handoff events in the feed.
 *
 * Shows what was passed between sessions (preflight brief, resume context,
 * follow-up handoff) so the user understands what the agent received.
 */

import { useState, memo } from "react";
import {
  ChevronDown, ChevronRight, Telescope, Link2, ArrowRightLeft, Zap,
} from "lucide-react";
import { cn } from "../lib/utils";
import { AgentMarkdown } from "./AgentMarkdown";
import type { ContextHandoff } from "../store/types";

const SOURCE_CONFIG: Record<string, { icon: typeof Telescope; label: string; accent: string }> = {
  preflight: {
    icon: Telescope,
    label: "Preflight Scout → Agent",
    accent: "text-purple-400/80 border-purple-500/20 bg-purple-500/[0.03]",
  },
  resume: {
    icon: ArrowRightLeft,
    label: "Previous Session → Agent",
    accent: "text-blue-400/80 border-blue-500/20 bg-blue-500/[0.03]",
  },
  resume_native: {
    icon: Link2,
    label: "SDK Session Resumed",
    accent: "text-emerald-400/80 border-emerald-500/20 bg-emerald-500/[0.03]",
  },
  followup: {
    icon: Zap,
    label: "Parent Job → Follow-up",
    accent: "text-amber-400/80 border-amber-500/20 bg-amber-500/[0.03]",
  },
};

export const HandoffCard = memo(function HandoffCard({ handoff }: { handoff: ContextHandoff }) {
  const [expanded, setExpanded] = useState(false);
  const config = SOURCE_CONFIG[handoff.source] ?? SOURCE_CONFIG.preflight!;
  const Icon = config.icon;

  return (
    <div className={cn(
      "rounded-lg border px-3 py-2 my-2",
      config.accent,
    )}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Icon size={13} className="shrink-0 opacity-80" />
        <span className="text-[11px] font-medium uppercase tracking-wide opacity-70">
          Context Handoff
        </span>
        <span className="text-[11px] text-muted-foreground/60 mx-1">·</span>
        <span className="text-[12px] text-muted-foreground/80 flex-1 min-w-0 truncate">
          {config.label}
        </span>
      </div>

      {/* Summary line */}
      <p className="text-[13px] text-foreground/70 mt-1.5 pl-[21px] leading-relaxed">
        {handoff.summary}
      </p>

      {/* Expand toggle (only if there's content to show) */}
      {handoff.content && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 mt-1.5 text-[11px] text-primary/60 hover:text-primary transition-colors pl-[21px]"
        >
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          {expanded ? "Hide brief" : "View full brief"}
        </button>
      )}

      {/* Expanded content */}
      {expanded && handoff.content && (
        <div className="mt-2 pt-2 border-t border-border/50 pl-[21px]">
          <div className="text-[13px] text-foreground/80 leading-relaxed max-h-64 overflow-y-auto">
            <AgentMarkdown content={handoff.content} />
          </div>
        </div>
      )}
    </div>
  );
});
