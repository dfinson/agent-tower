import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { JobSummary } from "../store";
import { StateBadge } from "./StateBadge";
import { SdkBadge } from "./SdkBadge";
import { MetadataChipStrip } from "./MetadataChipStrip";
import { JobActions, type JobActionsProps } from "./JobActions";
import { ConnectionStatusIndicator } from "./ConnectionStatusIndicator";
import { NavMenuSlideout } from "./NavMenuSlideout";

/** States where the card should default to expanded (user needs context/actions). */
const EXPAND_STATES = new Set(["review", "failed", "canceled", "completed"]);

interface JobHeaderCardProps {
  job: JobSummary;
  isPreparing: boolean;
  hasMergeConflict: boolean;
  onNavigateHome: () => void;
  onCostClick: () => void;
  actionProps: Omit<JobActionsProps, "layout">;
}

export function JobHeaderCard({
  job,
  isPreparing,
  hasMergeConflict,
  onNavigateHome,
  onCostClick,
  actionProps,
}: JobHeaderCardProps) {
  const shouldAutoExpand = EXPAND_STATES.has(job.state);
  const [expanded, setExpanded] = useState(shouldAutoExpand);
  const [userOverride, setUserOverride] = useState(false);

  // Auto-expand/collapse on state change unless user manually toggled
  useEffect(() => {
    if (!userOverride) {
      setExpanded(EXPAND_STATES.has(job.state));
    }
  }, [job.state, userOverride]);

  const toggle = () => {
    setExpanded((e) => !e);
    setUserOverride(true);
  };

  const isActive = ["running", "agent_running", "queued"].includes(job.state);

  return (
    <div className="shrink-0 border-b-2 border-border/60 bg-card/95">
      {/* ── Always-visible row: identity + collapsed summary ── */}
      <div className="flex items-center gap-2.5 h-12 px-4">
        <button onClick={onNavigateHome} className="flex items-center shrink-0 hover:opacity-80 transition-opacity">
          <img src="/mark.png" alt="" className="h-6 w-6 object-contain brightness-110 drop-shadow-[0_0_3px_rgba(255,255,255,0.08)]" />
        </button>
        <span className="text-muted-foreground/40 text-sm">/</span>
        <button onClick={toggle} className="flex items-center gap-1.5 min-w-0 hover:opacity-80 transition-opacity">
          {expanded
            ? <ChevronDown size={16} className="text-muted-foreground shrink-0" />
            : <ChevronRight size={16} className="text-muted-foreground shrink-0" />}
          <h1 className="text-base font-semibold text-foreground truncate">{job.title || job.id}</h1>
        </button>
        <span aria-live="polite"><StateBadge state={job.state} /></span>
        <span className="hidden lg:inline-flex"><SdkBadge sdk={job.sdk} /></span>

        {/* Collapsed inline hints — visible only when card body is hidden */}
        {!expanded && (
          <>
            {job.progressHeadline && isActive && (
              <span className="text-xs italic text-primary/70 truncate min-w-0">
                {job.progressHeadline}
              </span>
            )}
            {isPreparing && (
              <span className="text-xs text-violet-400 animate-pulse inline-flex items-center gap-1 shrink-0">
                <Loader2 size={12} className="animate-spin" />
                {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
              </span>
            )}
            {!isActive && !isPreparing && job.branch && (
              <span className="text-xs text-muted-foreground truncate min-w-0">
                {job.branch} → {job.baseRef}
              </span>
            )}
          </>
        )}

        <div className="flex-1 min-w-0" />
        <div className="flex items-center gap-1 shrink-0">
          <ConnectionStatusIndicator />
          <NavMenuSlideout />
        </div>
      </div>

      {/* ── Expanded card body ── */}
      {expanded && (
        <div className="px-4 pb-3.5 space-y-2.5">
          {/* Description / prompt */}
          {(job.description || job.prompt) && (
            <p className="text-sm text-foreground/70 line-clamp-2">{job.description ?? job.prompt}</p>
          )}

          {/* Metadata chips */}
          <MetadataChipStrip job={job} hasMergeConflict={hasMergeConflict} onCostClick={onCostClick} />

          {/* Current step / progress */}
          {job.progressHeadline && isActive && (
            <p className="text-xs italic text-primary/70 truncate">
              ● {job.progressHeadline}
            </p>
          )}
          {isPreparing && (
            <p className="text-xs text-violet-400 animate-pulse flex items-center gap-1">
              <Loader2 size={12} className="animate-spin" />
              {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
            </p>
          )}

          {/* Actions — inline with the rest of the card */}
          <JobActions {...actionProps} layout="bar" />
        </div>
      )}
    </div>
  );
}
