import { useState, useCallback, useRef, useEffect } from "react";
import { ExternalLink, XCircle, CheckCircle2, AlertTriangle, ArrowDownCircle, GitMerge, PanelLeftClose, PanelLeftOpen, Loader2, Radio, TerminalSquare, FolderTree, GitBranch, BarChart3, Package } from "lucide-react";
import type { JobSummary } from "../store";
import { ActivityTimeline } from "./ActivityTimeline";
import { JobActions } from "./JobActions";
import { Tooltip } from "./ui/tooltip";
import { cn } from "../lib/utils";

// ── Tab definitions for the sidebar nav ──
const TAB_ITEMS = [
  { id: "live", icon: Radio, label: "Live" },
  { id: "shell", icon: TerminalSquare, label: "Shell" },
  { id: "files", icon: FolderTree, label: "Files" },
  { id: "diff", icon: GitBranch, label: "Changes", conditional: true },
  { id: "metrics", icon: BarChart3, label: "Metrics" },
  { id: "artifacts", icon: Package, label: "Artifacts", conditional: true },
] as const;

interface JobDetailSidebarProps {
  job: JobSummary;
  jobId: string;
  selectedTurnId: string | null;
  searchActive: boolean;
  visibleStepTurnId: string | null;
  onStepClick: (turnId: string) => void;
  hasMergeConflict: boolean;
  unresolvedResolutionError: string | null;
  // Tab navigation
  activeTab: string;
  onTabChange: (tab: string) => void;
  hasChanges: boolean;
  hasArtifacts: boolean;
  artifactCount: number;
  // Actions
  canCancel: boolean;
  canResume: boolean;
  needsResolution: boolean;
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
  // Terminal
  hasWorktree: boolean;
  jobTerminalCount: number;
  onOpenTerminal: () => void;
}

export function JobDetailSidebar({
  job,
  jobId,
  selectedTurnId,
  searchActive,
  visibleStepTurnId,
  onStepClick,
  hasMergeConflict,
  unresolvedResolutionError,
  activeTab,
  onTabChange,
  hasChanges,
  hasArtifacts,
  artifactCount,
  canCancel,
  canResume,
  needsResolution,
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
  hasWorktree,
  jobTerminalCount,
  onOpenTerminal,
}: JobDetailSidebarProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => Math.max(240, Math.min(360, window.innerWidth * 0.18)));
  const isResizingRef = useRef(false);
  const resizeCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => { resizeCleanupRef.current?.(); }, []);

  const handleSidebarResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizingRef.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizingRef.current) return;
      const delta = ev.clientX - startX;
      const newWidth = Math.max(160, Math.min(480, startWidth + delta));
      setSidebarWidth(newWidth);
    };
    const onMouseUp = () => {
      isResizingRef.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      resizeCleanupRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    resizeCleanupRef.current = onMouseUp;
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [sidebarWidth]);

  const isPreparing = job.state === "preparing";

  // Filter visible tabs based on conditional flags
  const visibleTabs = TAB_ITEMS.filter((t) => {
    if (t.id === "diff") return hasChanges;
    if (t.id === "artifacts") return hasArtifacts;
    return true;
  });

  return (
    <>
      {/* ── Icon-only rail at md, full sidebar at lg+ ── */}

      {/* Icon rail (md only, when full sidebar would be hidden) */}
      <div className="hidden md:flex lg:hidden flex-col items-center gap-1 py-2 px-1 shrink-0 border-r border-border bg-card">
        {visibleTabs.map(({ id, icon: Icon, label }) => (
          <Tooltip key={id} content={label}>
            <button
              onClick={() => onTabChange(id)}
              className={cn(
                "flex items-center justify-center w-9 h-9 rounded-md transition-colors",
                activeTab === id
                  ? "bg-accent text-primary"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
              )}
            >
              <Icon size={18} />
            </button>
          </Tooltip>
        ))}
        {hasWorktree && (
          <>
            <div className="w-5 h-px bg-border my-1" />
            <Tooltip content={jobTerminalCount > 0 ? `Open new terminal (${jobTerminalCount} open)` : "Open terminal in worktree"}>
              <button
                onClick={onOpenTerminal}
                className="flex items-center justify-center w-9 h-9 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors relative"
              >
                <TerminalSquare size={18} />
                {jobTerminalCount > 0 && (
                  <span className="absolute top-1 right-1 text-[9px] font-bold text-primary">{jobTerminalCount}</span>
                )}
              </button>
            </Tooltip>
          </>
        )}
        <div className="flex-1" />
        <Tooltip content={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <button
            onClick={() => setSidebarCollapsed((c) => !c)}
            className="flex items-center justify-center w-9 h-9 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </Tooltip>
      </div>

      {/* Full sidebar (lg+) */}
      <div
        className={cn(
          "hidden lg:flex flex-col flex-shrink-0 md:h-full min-h-[22rem] rounded-lg border border-border bg-card overflow-hidden",
          sidebarCollapsed && "w-10",
        )}
        style={sidebarCollapsed ? undefined : { width: sidebarWidth }}
      >
        {sidebarCollapsed ? (
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex items-center justify-center h-full text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
            title="Expand sidebar"
          >
            <PanelLeftOpen size={18} />
          </button>
        ) : (
          <>
            {/* ── Tab navigation ── */}
            <nav className="flex flex-col gap-0.5 px-2 pt-2 pb-1 shrink-0">
              {visibleTabs.map(({ id, icon: Icon, label }) => (
                <button
                  key={id}
                  onClick={() => onTabChange(id)}
                  className={cn(
                    "flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm font-medium transition-colors",
                    activeTab === id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                  )}
                >
                  <Icon size={15} className="shrink-0" />
                  <span className="truncate">{label}</span>
                  {id === "artifacts" && artifactCount > 0 && (
                    <span className="ml-auto text-[10px] leading-none bg-muted text-muted-foreground rounded-full px-1.5 py-0.5 font-normal">
                      {artifactCount}
                    </span>
                  )}
                </button>
              ))}
              {hasWorktree && (
                <button
                  onClick={onOpenTerminal}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                >
                  <TerminalSquare size={15} className="shrink-0" />
                  <span>Terminal</span>
                  {jobTerminalCount > 0 && (
                    <span className="ml-auto text-[10px] font-semibold text-primary">×{jobTerminalCount}</span>
                  )}
                </button>
              )}
            </nav>

            <div className="h-px bg-border mx-2" />

            {/* ── Activity timeline — takes remaining space ── */}
            <button
              onClick={() => setSidebarCollapsed(true)}
              className="flex items-center gap-2 px-4 py-2 w-full text-left hover:bg-accent/50 transition-colors shrink-0"
              title="Collapse sidebar"
            >
              <PanelLeftClose size={13} className="text-muted-foreground shrink-0" />
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Activity</span>
            </button>
            <div className="flex-1 overflow-hidden">
              <ActivityTimeline
                jobId={jobId}
                jobState={job.state}
                onStepClick={onStepClick}
                selectedTurnId={selectedTurnId}
                searchActive={searchActive}
                visibleStepTurnId={visibleStepTurnId}
              />
            </div>

            <div className="h-px bg-border" />

            {/* ── Job metadata ── */}
            <div className="px-3 py-2 border-t border-border space-y-1.5 text-xs shrink-0 overflow-y-auto max-h-[35%]">
              {(job.description || job.prompt) && (
                <p className="text-muted-foreground line-clamp-3 text-[12px]">{job.description ?? job.prompt}</p>
              )}
              <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                {[
                  ["Branch", job.branch ?? "—"],
                  ["Base", job.baseRef],
                  ...(job.model ? [["Model", job.model]] : []),
                  ["Created", new Date(job.createdAt).toLocaleString()],
                  ...(job.completedAt ? [["Done", new Date(job.completedAt).toLocaleString()]] : []),
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0">
                    <p className="text-[10px] text-muted-foreground/70 uppercase font-semibold tracking-wide">{label}</p>
                    <p className="text-[12px] text-foreground/80 truncate" title={String(value)}>{value}</p>
                  </div>
                ))}
              </div>
              {job.prUrl && (
                <a href={job.prUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
                  <ExternalLink size={11} /> Pull Request
                </a>
              )}
              {/* Status banners — compact in sidebar */}
              {job.modelDowngraded && (
                <div className="flex items-start gap-1.5 rounded border border-amber-500/30 bg-amber-500/10 p-1.5">
                  <ArrowDownCircle size={13} className="text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-[11px] font-medium text-amber-500">Model downgraded</p>
                    <p className="text-[11px] text-amber-400">
                      {job.requestedModel} → {job.actualModel}
                    </p>
                  </div>
                </div>
              )}
              {job.state === "failed" && (
                <div className="flex items-start gap-1.5 rounded border border-red-500/30 bg-red-500/10 p-1.5">
                  <XCircle size={13} className="text-red-500 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-[11px] font-medium text-red-500">Failed</p>
                    <p className="text-[11px] text-red-400 line-clamp-2">{job.failureReason ?? "No details"}</p>
                  </div>
                </div>
              )}
              {job.state === "review" && (() => {
                const isConflict = hasMergeConflict;
                const isSignOff = job.resolution === "unresolved" || !job.resolution;
                return (
                  <div className={`flex items-start gap-1.5 rounded border p-1.5 ${isConflict ? "border-amber-500/30 bg-amber-500/10" : isSignOff ? "border-blue-500/30 bg-blue-500/10" : "border-green-500/30 bg-green-500/10"}`}>
                    {isConflict ? (
                      <AlertTriangle size={13} className="text-amber-500 shrink-0 mt-0.5" />
                    ) : isSignOff ? (
                      <GitMerge size={13} className="text-blue-500 shrink-0 mt-0.5" />
                    ) : (
                      <CheckCircle2 size={13} className="text-green-500 shrink-0 mt-0.5" />
                    )}
                    <p className={`text-[11px] font-medium ${isConflict ? "text-amber-500" : isSignOff ? "text-blue-500" : "text-green-500"}`}>
                      {isConflict ? "Merge conflict" : isSignOff ? "Review required" : "Ready"}
                    </p>
                    {unresolvedResolutionError && (
                      <p className="text-[11px] text-blue-300/90">Merge failed: {unresolvedResolutionError}</p>
                    )}
                  </div>
                );
              })()}
              {job.state === "completed" && (
                <div className="flex items-start gap-1.5 rounded border border-green-500/30 bg-green-500/10 p-1.5">
                  <CheckCircle2 size={13} className="text-green-500 shrink-0 mt-0.5" />
                  <p className="text-[11px] font-medium text-green-500">
                    {job.resolution === "merged" ? "Merged"
                      : job.resolution === "pr_created" ? "PR created"
                      : job.resolution === "discarded" ? "Discarded"
                      : "Completed"}
                  </p>
                </div>
              )}
              {job.state === "canceled" && (
                <div className="flex items-start gap-1.5 rounded border border-amber-500/30 bg-amber-500/10 p-1.5">
                  <AlertTriangle size={13} className="text-amber-500 shrink-0 mt-0.5" />
                  <p className="text-[11px] font-medium text-amber-500">Canceled</p>
                </div>
              )}
              {isPreparing && (
                <div className="flex items-start gap-1.5 rounded border border-violet-500/30 bg-violet-500/10 p-1.5">
                  <Loader2 size={13} className="text-violet-400 shrink-0 mt-0.5 animate-spin" />
                  <p className="text-[11px] font-medium text-violet-400">
                    {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
                  </p>
                </div>
              )}
              {/* ── Actions ── */}
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
                onCancelOpen={onCancelOpen}
                onResume={onResume}
                onResolve={onResolve}
                onDiscardOpen={onDiscardOpen}
                onMarkDoneOpen={onMarkDoneOpen}
                onCompleteOpen={onCompleteOpen}
                layout="compact"
              />
            </div>
          </>
        )}
      </div>
      {/* Drag handle for resizing sidebar */}
      {!sidebarCollapsed && (
        <div
          className="hidden lg:flex items-center justify-center w-2 cursor-col-resize group flex-shrink-0"
          onMouseDown={handleSidebarResizeStart}
          title="Drag to resize"
        >
          <div className="w-0.5 h-8 rounded-full bg-border group-hover:bg-muted-foreground/60 transition-colors" />
        </div>
      )}
    </>
  );
}
