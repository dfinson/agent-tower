import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { JobSummary } from "../store";
import { StateBadge } from "./StateBadge";
import { SdkBadge } from "./SdkBadge";
import { MetadataChipStrip } from "./MetadataChipStrip";
import { JobActions, type JobActionsProps } from "./JobActions";
import { ConnectionStatusIndicator } from "./ConnectionStatusIndicator";
import { NavMenuSlideout } from "./NavMenuSlideout";
import { BottomSheet } from "./ui/bottom-sheet";

/** States where the card should default to expanded (user needs context/actions). */
const EXPAND_STATES = new Set(["review", "failed", "canceled", "completed"]);

/** Top accent color keyed by job state. */
const ACCENT: Record<string, string> = {
  preparing: "border-t-violet-500/60",
  queued: "border-t-yellow-500/60",
  running: "border-t-blue-500/60",
  waiting_for_approval: "border-t-orange-500/60",
  review: "border-t-cyan-500/60",
  completed: "border-t-green-500/60",
  failed: "border-t-red-500/60",
  canceled: "border-t-gray-500/40",
};

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
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    if (!userOverride) {
      setExpanded(EXPAND_STATES.has(job.state));
    }
  }, [job.state, userOverride]);

  const toggleDesktop = () => {
    setExpanded((e) => !e);
    setUserOverride(true);
  };

  const isActive = ["running", "agent_running", "queued"].includes(job.state);
  const accent = ACCENT[job.state] ?? "border-t-gray-500/40";

  return (
    <>
      {/* ────────────────────────────────────────────────────────────────── */}
      {/* Mobile (< md): compact accent rail — tap title to open sheet     */}
      {/* ────────────────────────────────────────────────────────────────── */}
      <div className={`md:hidden shrink-0 border-t-2 ${accent} border-b border-border/50 bg-card shadow-sm`}>
        <div className="flex items-center gap-2.5 h-11 px-3">
          <button onClick={onNavigateHome} className="shrink-0 hover:opacity-80 transition-opacity" aria-label="Back to dashboard">
            <img src="/mark.png" alt="" className="h-6 w-6 object-contain brightness-110 drop-shadow-[0_0_3px_rgba(255,255,255,0.08)]" />
          </button>

          <button onClick={() => setSheetOpen(true)} className="flex items-center gap-1.5 min-w-0">
            <h1 className="text-sm font-semibold text-foreground truncate">{job.title || job.id}</h1>
          </button>

          <span aria-live="polite"><StateBadge state={job.state} /></span>

          <div className="flex-1" />
          <div className="flex items-center gap-1.5 shrink-0">
            <ConnectionStatusIndicator />
            <NavMenuSlideout />
          </div>
        </div>
      </div>

      {/* Mobile bottom sheet — full job detail view */}
      <BottomSheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Job Details">
        <div className="space-y-3">
          <div>
            <h2 className="text-base font-bold text-foreground break-words">{job.title || job.id}</h2>
            {job.title && <p className="text-xs text-muted-foreground font-mono mt-0.5">{job.id}</p>}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <StateBadge state={job.state} />
            <SdkBadge sdk={job.sdk} />
          </div>

          {(job.description || job.prompt) && (
            <p className="text-sm text-muted-foreground">{job.description ?? job.prompt}</p>
          )}

          {job.progressHeadline && isActive && (
            <p className="text-sm italic text-primary/70">{job.progressHeadline}</p>
          )}
          {isPreparing && (
            <div className="flex items-center gap-2 text-sm text-violet-400 animate-pulse">
              <Loader2 size={14} className="animate-spin" />
              {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
            </div>
          )}

          <MetadataChipStrip job={job} hasMergeConflict={hasMergeConflict} onCostClick={() => { setSheetOpen(false); onCostClick(); }} />

          <div className="pt-2 border-t border-border">
            <JobActions
              {...actionProps}
              onCancelOpen={() => { setSheetOpen(false); actionProps.onCancelOpen(); }}
              onResume={() => { setSheetOpen(false); actionProps.onResume(); }}
              onResolve={(a) => { setSheetOpen(false); actionProps.onResolve(a); }}
              onDiscardOpen={() => { setSheetOpen(false); actionProps.onDiscardOpen(); }}
              onMarkDoneOpen={() => { setSheetOpen(false); actionProps.onMarkDoneOpen(); }}
              onCompleteOpen={() => { setSheetOpen(false); actionProps.onCompleteOpen(); }}
              layout="full"
            />
          </div>
        </div>
      </BottomSheet>

      {/* ────────────────────────────────────────────────────────────────── */}
      {/* Desktop (>= md): inline collapsible card                         */}
      {/* ────────────────────────────────────────────────────────────────── */}
      <div className={`hidden md:block shrink-0 rounded-t-lg border-t-[3px] ${accent} border-b border-border bg-card/95 backdrop-blur-sm shadow-md`}>
        {/* ── Row 1: identity bar ── */}
        <div className="flex items-center gap-3 px-4 pt-3 pb-1.5">
          <button onClick={onNavigateHome} className="shrink-0 hover:opacity-80 transition-opacity" aria-label="Back to dashboard">
            <img src="/mark.png" alt="" className="h-7 w-7 object-contain brightness-110 drop-shadow-[0_0_3px_rgba(255,255,255,0.08)]" />
          </button>

          <button onClick={toggleDesktop} className="flex items-center gap-2 min-w-0 group">
            {expanded
              ? <ChevronDown size={16} className="text-muted-foreground shrink-0 group-hover:text-foreground transition-colors" />
              : <ChevronRight size={16} className="text-muted-foreground shrink-0 group-hover:text-foreground transition-colors" />}
            <h1 className="text-base lg:text-lg font-semibold text-foreground truncate">{job.title || job.id}</h1>
          </button>

          <span aria-live="polite"><StateBadge state={job.state} /></span>
          <SdkBadge sdk={job.sdk} />

          {/* Collapsed inline context */}
          {!expanded && (
            <span className="text-xs text-muted-foreground/70 truncate min-w-0">
              {job.progressHeadline && isActive
                ? job.progressHeadline
                : isPreparing
                  ? (job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…")
                  : job.branch
                    ? `${job.branch} → ${job.baseRef}`
                    : null}
            </span>
          )}

          <div className="flex-1" />
          <div className="flex items-center gap-1.5 shrink-0">
            <ConnectionStatusIndicator />
            <NavMenuSlideout />
          </div>
        </div>

        {/* ── Expanded body ── */}
        {expanded && (
          <div className="px-4 pb-3 space-y-2.5">
            {(job.description || job.prompt) && (
              <p className="text-sm text-foreground/60 line-clamp-2 pl-10">{job.description ?? job.prompt}</p>
            )}

            {job.progressHeadline && isActive && (
              <p className="text-xs italic text-primary/70 truncate pl-10">
                ● {job.progressHeadline}
              </p>
            )}
            {isPreparing && (
              <p className="text-xs text-violet-400 animate-pulse flex items-center gap-1 pl-10">
                <Loader2 size={12} className="animate-spin" />
                {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2 pl-10">
              <MetadataChipStrip job={job} hasMergeConflict={hasMergeConflict} onCostClick={onCostClick} />
              <div className="flex-1" />
              <JobActions {...actionProps} layout="bar" />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
