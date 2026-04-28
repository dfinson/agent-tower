import { useState, useCallback, useRef, useEffect } from "react";
import { ExternalLink, XCircle, CheckCircle2, AlertTriangle, ArrowDownCircle, GitMerge, PanelLeftClose, PanelLeftOpen, Loader2 } from "lucide-react";
import type { JobSummary } from "../store";
import { ActivityTimeline } from "./ActivityTimeline";
import { cn } from "../lib/utils";

interface JobDetailSidebarProps {
  job: JobSummary;
  jobId: string;
  selectedTurnId: string | null;
  searchActive: boolean;
  visibleStepTurnId: string | null;
  onStepClick: (turnId: string) => void;
  hasMergeConflict: boolean;
  unresolvedResolutionError: string | null;
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

  return (
    <>
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
            title="Expand activity timeline"
          >
            <PanelLeftOpen size={18} />
          </button>
        ) : (
          <>
            <button
              onClick={() => setSidebarCollapsed(true)}
              className="flex items-center gap-2 px-4 py-2.5 w-full text-left border-b border-border hover:bg-accent/50 transition-colors"
              title="Collapse activity timeline"
            >
              <PanelLeftClose size={13} className="text-muted-foreground shrink-0" />
              <span className="text-sm font-semibold text-muted-foreground">Activity</span>
            </button>
            {/* ── Job metadata panel ── */}
            <div className="px-3 py-2 border-b border-border space-y-1.5 text-xs shrink-0 overflow-y-auto max-h-[40%]">
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
            </div>
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
