import { ArrowLeft, RotateCcw, XCircle, ExternalLink, GitMerge, GitPullRequest, Trash2, FolderTree, FolderGit2, GitBranch, TerminalSquare, MoreHorizontal, ListTree, Radio, Package, Loader2, BarChart3 } from "lucide-react";
import type { JobSummary } from "../store";
import { StateBadge } from "./StateBadge";
import { SdkBadge } from "./SdkBadge";
import { Button } from "./ui/button";
import { BottomSheet } from "./ui/bottom-sheet";
import { JobActions } from "./JobActions";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "../lib/utils";

// ────────────────────────────────────────────────────────────────────────────
// MobileStatusRail — compact header bar visible only below md breakpoint
// ────────────────────────────────────────────────────────────────────────────

interface MobileStatusRailProps {
  job: JobSummary;
  onBack: () => void;
  onOpenDetail: () => void;
  onCancelOpen: () => void;
  onResume: () => void;
  onOpenTerminal: () => void;
  canCancel: boolean;
  canResume: boolean;
  hasWorktree: boolean;
  jobTerminalCount: number;
}

export function MobileStatusRail({
  job,
  onBack,
  onOpenDetail,
  onCancelOpen,
  onResume,
  onOpenTerminal,
  canCancel,
  canResume,
  hasWorktree,
  jobTerminalCount,
}: MobileStatusRailProps) {
  return (
    <div className="flex md:hidden items-center gap-2 h-10 px-2 border-b border-border bg-card shrink-0">
      <button onClick={onBack} className="p-1.5 -ml-1 text-muted-foreground hover:text-foreground transition-colors" aria-label="Back to dashboard">
        <ArrowLeft size={16} />
      </button>
      <button
        onClick={onOpenDetail}
        className="flex-1 min-w-0 flex items-center gap-2 text-left"
      >
        <span className="text-sm font-semibold text-foreground truncate">
          {job.title || job.id}
        </span>
      </button>
      <span aria-live="polite"><StateBadge state={job.state} /></span>
      <PopoverPrimitive.Root>
        <PopoverPrimitive.Trigger asChild>
          <button aria-label="Job actions" className="p-1.5 text-muted-foreground hover:text-foreground transition-colors">
            <MoreHorizontal size={16} />
          </button>
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            side="bottom"
            align="end"
            sideOffset={4}
            className="z-50 min-w-[160px] rounded-md border border-border bg-popover p-1 shadow-md animate-in fade-in-0 zoom-in-95"
          >
            {canCancel && (
              <button
                onClick={onCancelOpen}
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-destructive transition-colors hover:bg-accent"
              >
                <XCircle size={13} /> Cancel Job
              </button>
            )}
            {canResume && (
              <button
                onClick={onResume}
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <RotateCcw size={13} /> Resume
              </button>
            )}
            {hasWorktree && (
              <button
                onClick={onOpenTerminal}
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <TerminalSquare size={13} /> Terminal
                {jobTerminalCount > 0 && <span className="ml-auto text-[10px] font-semibold text-primary">×{jobTerminalCount}</span>}
              </button>
            )}
            <button
              onClick={onOpenDetail}
              className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <FolderGit2 size={13} /> Job Details
            </button>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// MobileJobDetailSheet — bottom sheet with full job metadata + action buttons
// ────────────────────────────────────────────────────────────────────────────

interface MobileJobDetailSheetProps {
  job: JobSummary;
  open: boolean;
  onClose: () => void;
  isPreparing: boolean;
  canCancel: boolean;
  canResume: boolean;
  needsResolution: boolean;
  hasChanges: boolean;
  hasMergeConflict: boolean;
  isResolved: boolean;
  canArchive: boolean;
  actionLoading: boolean;
  resolveLoading: string | null;
  onCancelOpen: () => void;
  onResume: () => void;
  onResolve: (action: "merge" | "smart_merge" | "create_pr" | "agent_merge") => void;
  onDiscardOpen: () => void;
  onMarkDoneOpen: () => void;
  onCompleteOpen: () => void;
}

export function MobileJobDetailSheet({
  job,
  open,
  onClose,
  isPreparing,
  canCancel,
  canResume,
  needsResolution,
  hasChanges,
  hasMergeConflict,
  isResolved,
  canArchive,
  actionLoading,
  resolveLoading,
  onCancelOpen,
  onResume,
  onResolve,
  onDiscardOpen,
  onMarkDoneOpen,
  onCompleteOpen,
}: MobileJobDetailSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} title="Job Details">
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
        {job.progressHeadline && ["running", "agent_running", "queued"].includes(job.state) && (
          <p className="text-sm italic text-primary/70">{job.progressHeadline}</p>
        )}
        {isPreparing && (
          <div className="flex items-center gap-2 text-sm text-violet-400 animate-pulse">
            <Loader2 size={14} className="animate-spin" />
            {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up workspace…"}
          </div>
        )}
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {[
            ["Branch", job.branch ?? "—"],
            ["Base", job.baseRef],
            ["Repo", job.repo.split("/").pop() ?? job.repo],
            ...(job.model ? [["Model", job.model]] : []),
            ["Created", new Date(job.createdAt).toLocaleString()],
            ...(job.completedAt ? [["Completed", new Date(job.completedAt).toLocaleString()]] : []),
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-xs text-muted-foreground uppercase font-semibold tracking-wide">{label}</p>
              <p className="text-sm break-all">{value}</p>
            </div>
          ))}
        </div>
        {job.prUrl && (
          <a href={job.prUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
            <ExternalLink size={14} /> View Pull Request
          </a>
        )}
        {/* Action buttons in sheet */}
        <div className="pt-2 border-t border-border">
          <JobActions
            canCancel={canCancel}
            canResume={canResume}
            needsResolution={needsResolution}
            hasChanges={hasChanges}
            hasMergeConflict={hasMergeConflict}
            isResolved={isResolved}
            canArchive={canArchive}
            jobState={job.state}
            archivedAt={job.archivedAt}
            actionLoading={actionLoading}
            resolveLoading={resolveLoading}
            onCancelOpen={() => { onClose(); onCancelOpen(); }}
            onResume={() => { onClose(); onResume(); }}
            onResolve={(action) => { onClose(); onResolve(action); }}
            onDiscardOpen={() => { onClose(); onDiscardOpen(); }}
            onMarkDoneOpen={() => { onClose(); onMarkDoneOpen(); }}
            onCompleteOpen={() => { onClose(); onCompleteOpen(); }}
            layout="full"
          />
        </div>
      </div>
    </BottomSheet>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// MobileBottomNav — iOS-style tab bar fixed at bottom
// ────────────────────────────────────────────────────────────────────────────

interface MobileBottomNavProps {
  tab: string;
  handleTabChange: (tab: string) => void;
  hasChanges: boolean;
  hasArtifacts: boolean;
  artifactCount: number;
  mobileActivityOpen: boolean;
  setMobileActivityOpen: (open: boolean | ((o: boolean) => boolean)) => void;
  mobileMoreOpen: boolean;
  setMobileMoreOpen: (open: boolean | ((o: boolean) => boolean)) => void;
}

export function MobileBottomNav({
  tab,
  handleTabChange,
  hasChanges,
  hasArtifacts,
  artifactCount,
  mobileActivityOpen,
  setMobileActivityOpen,
  mobileMoreOpen,
  setMobileMoreOpen,
}: MobileBottomNavProps) {
  return (
    <nav className="fixed bottom-0 inset-x-0 z-50 md:hidden flex items-end justify-around border-t border-border bg-card/95 backdrop-blur-sm safe-area-pb landscape:items-center" style={{ height: 52 }}>
      {/* Activity toggle — visually distinct (opens overlay, not a tab) */}
      <button
        onClick={() => { if (tab !== "live") handleTabChange("live"); setMobileActivityOpen((o: boolean) => !o); setMobileMoreOpen(false); }}
        className={cn(
          "flex flex-col items-center justify-center gap-0.5 flex-1 pt-1.5 pb-1 min-w-0 transition-colors landscape:flex-row landscape:gap-1 landscape:py-0.5",
          mobileActivityOpen ? "text-primary" : "text-muted-foreground active:text-foreground",
        )}
      >
        <ListTree size={20} strokeWidth={mobileActivityOpen ? 2.5 : 1.5} className="landscape:!size-4" />
        <span className={cn("text-[10px] leading-tight truncate landscape:hidden", mobileActivityOpen && "font-semibold")}>Activity</span>
      </button>
      {[
        { id: "live", icon: Radio, label: "Live" },
        ...(hasChanges ? [{ id: "diff", icon: GitBranch, label: "Changes" }] : []),
        { id: "files", icon: FolderTree, label: "Files" },
      ].map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          onClick={() => { setMobileActivityOpen(false); setMobileMoreOpen(false); handleTabChange(id); }}
          className={cn(
            "flex flex-col items-center justify-center gap-0.5 flex-1 pt-1.5 pb-1 min-w-0 transition-colors landscape:flex-row landscape:gap-1 landscape:py-0.5",
            tab === id && !mobileActivityOpen
              ? "text-primary"
              : "text-muted-foreground active:text-foreground",
          )}
        >
          <Icon size={20} strokeWidth={tab === id && !mobileActivityOpen ? 2.5 : 1.5} className="landscape:!size-4" />
          <span className={cn("text-[10px] leading-tight truncate landscape:hidden", tab === id && !mobileActivityOpen && "font-semibold")}>{label}</span>
        </button>
      ))}
      {/* More overflow — Shell, Metrics, Artifacts */}
      <div className="relative flex-1 min-w-0">
        <button
          onClick={() => setMobileMoreOpen((o: boolean) => !o)}
          className={cn(
            "flex flex-col items-center justify-center gap-0.5 w-full pt-1.5 pb-1 transition-colors landscape:flex-row landscape:gap-1 landscape:py-0.5",
            mobileMoreOpen || ["shell", "metrics", "artifacts"].includes(tab) ? "text-primary" : "text-muted-foreground active:text-foreground",
          )}
        >
          <MoreHorizontal size={20} strokeWidth={mobileMoreOpen || ["shell", "metrics", "artifacts"].includes(tab) ? 2.5 : 1.5} className="landscape:!size-4" />
          <span className={cn("text-[10px] leading-tight truncate landscape:hidden", (mobileMoreOpen || ["shell", "metrics", "artifacts"].includes(tab)) && "font-semibold")}>More</span>
        </button>
        {mobileMoreOpen && (
          <div className="absolute bottom-full right-0 mb-2 mr-1 rounded-md border border-border bg-popover shadow-lg py-1 min-w-[140px] animate-in fade-in-0 zoom-in-95">
            <button
              onClick={() => { setMobileMoreOpen(false); setMobileActivityOpen(false); handleTabChange("shell"); }}
              className={cn("flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors", tab === "shell" ? "text-primary bg-accent" : "text-foreground hover:bg-accent")}
            >
              <TerminalSquare size={15} /> Shell
            </button>
            <button
              onClick={() => { setMobileMoreOpen(false); setMobileActivityOpen(false); handleTabChange("metrics"); }}
              className={cn("flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors", tab === "metrics" ? "text-primary bg-accent" : "text-foreground hover:bg-accent")}
            >
              <BarChart3 size={15} /> Metrics
            </button>
            {hasArtifacts && (
              <button
                onClick={() => { setMobileMoreOpen(false); setMobileActivityOpen(false); handleTabChange("artifacts"); }}
                className={cn("flex w-full items-center gap-2.5 px-3 py-2.5 text-sm transition-colors", tab === "artifacts" ? "text-primary bg-accent" : "text-foreground hover:bg-accent")}
              >
                <Package size={15} /> Artifacts
                {artifactCount > 0 && <span className="ml-auto text-[10px] font-semibold text-primary">{artifactCount}</span>}
              </button>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// MobileFooterActions — contextual review actions above the bottom nav
// ────────────────────────────────────────────────────────────────────────────

interface MobileFooterActionsProps {
  needsResolution: boolean;
  hasChanges: boolean;
  tab: string;
  hasMergeConflict: boolean;
  resolveLoading: string | null;
  onResolve: (action: "merge" | "smart_merge" | "create_pr" | "agent_merge") => void;
  onDiscardOpen: () => void;
}

export function MobileFooterActions({
  needsResolution,
  hasChanges,
  tab,
  hasMergeConflict,
  resolveLoading,
  onResolve,
  onDiscardOpen,
}: MobileFooterActionsProps) {
  if (!(needsResolution && hasChanges && tab === "diff")) return null;

  return (
    <div className="fixed bottom-[52px] inset-x-0 z-40 flex md:hidden items-center justify-center gap-2 px-3 py-2 border-t border-border bg-card/95 backdrop-blur-sm">
      {!hasMergeConflict && (
        <Button size="sm" className="flex-1 gap-1" loading={resolveLoading === "smart_merge"} disabled={resolveLoading !== null} onClick={() => onResolve("smart_merge")}>
          <GitMerge size={14} /> Merge
        </Button>
      )}
      {hasMergeConflict && (
        <Button size="sm" className="flex-1 gap-1" loading={resolveLoading === "agent_merge"} disabled={resolveLoading !== null} onClick={() => onResolve("agent_merge")}>
          <GitMerge size={14} /> Resolve
        </Button>
      )}
      <Button size="sm" variant="outline" className="flex-1 gap-1" loading={resolveLoading === "create_pr"} disabled={resolveLoading !== null} onClick={() => onResolve("create_pr")}>
        <GitPullRequest size={14} /> PR
      </Button>
      <Button size="sm" variant="outline" className="gap-1 text-destructive border-destructive/40" onClick={onDiscardOpen}>
        <Trash2 size={14} />
      </Button>
    </div>
  );
}
