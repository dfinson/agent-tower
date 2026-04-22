import { useEffect, useState, useCallback, useRef, useMemo, Suspense, Component, type ReactNode } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, RotateCcw, XCircle, ExternalLink, CheckCircle2, AlertTriangle, ArrowDownCircle, GitMerge, GitPullRequest, Trash2, Archive, FolderTree, FolderGit2, GitBranch, TerminalSquare, MoreHorizontal, PanelLeftClose, PanelLeftOpen, BarChart3, ListTree, Radio, Package, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useStore, selectJobs, enrichJob, selectJobDiffs } from "../store";
import type { JobSummary } from "../store";
import { useSSE } from "../hooks/useSSE";
import { formatJobTerminalLabel } from "../lib/terminalLabels";
import { fetchJob, cancelJob, fetchJobTranscript, fetchJobDiff, fetchApprovals, resolveJob, fetchArtifacts, resumeJob, archiveJob, fetchJobSnapshot } from "../api/client";
import { CuratedFeed } from "./CuratedFeed";
import { ActivityTimeline } from "./ActivityTimeline";
import { lazyRetry } from "../lib/lazyRetry";
import { StateBadge } from "./StateBadge";
import { SdkBadge } from "./SdkBadge";
import { MetricsPanel } from "./MetricsPanel";
import { CompleteJobDialog } from "./CompleteJobDialog";
import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";
import { JobDetailSkeleton } from "./JobDetailSkeleton";
import { Tooltip } from "./ui/tooltip";
import { ConfirmDialog } from "./ui/confirm-dialog";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "../lib/utils";
import { BottomSheet } from "./ui/bottom-sheet";
import type { StepFilter } from "./DiffViewer";

const WorkspaceBrowser = lazyRetry(() => import("./WorkspaceBrowser"));
const DiffViewer = lazyRetry(() => import("./DiffViewer"));
const ArtifactViewer = lazyRetry(() => import("./ArtifactViewer"));
const AgentTerminal = lazyRetry(() => import("./AgentTerminal").then((m) => ({ default: m.AgentTerminal })));

const SKELETON_DELAY_MS = 500;

/** Error boundary for lazy-loaded tabs — shows a recovery button instead of a blank panel. */
class TabErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <p className="text-sm text-muted-foreground">This panel failed to load.</p>
          <button
            onClick={() => this.setState({ error: null })}
            className="px-3 py-1.5 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}


export function JobDetailScreen() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const jobs = useStore(selectJobs);
  const job: JobSummary | undefined = jobId ? jobs[jobId] : undefined;
  const [loading, setLoading] = useState(!job);
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [resolveLoading, setResolveLoading] = useState<string | null>(null);
  const [completeOpen, setCompleteOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [markDoneOpen, setMarkDoneOpen] = useState(false);
  const [tab, setTab] = useState("live");
  const [stepFilter, setStepFilter] = useState<StepFilter | null>(null);
  const [scrollToSeq, setScrollToSeq] = useState<number | null>(null);
  const [scrollToTurnId, setScrollToTurnId] = useState<string | null>(null);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [searchActive, setSearchActive] = useState(false);
  const [visibleTurnId, setVisibleTurnId] = useState<string | null>(null);
  // Reset selectedTurnId when navigating to a different job
  useEffect(() => { setSelectedTurnId(null); setSearchActive(false); setVisibleTurnId(null); }, [jobId]);
  // Update document title to show job identity in browser tabs
  useEffect(() => {
    const label = job?.title || jobId || "";
    if (label) {
      document.title = `${label} — CodePlane`;
    }
    return () => { document.title = "CodePlane"; };
  }, [job?.title, jobId]);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [mobileActivityOpen, setMobileActivityOpen] = useState(false);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => Math.max(240, Math.min(360, window.innerWidth * 0.18)));
  const isResizingRef = useRef(false);
  const diffs = useStore(selectJobDiffs(jobId ?? ""));
  const hasChanges = diffs.length > 0;
  const hasWorktree = !!job?.worktreePath && !job?.archivedAt;
  const [hasArtifacts, setHasArtifacts] = useState(false);
  const [artifactCount, setArtifactCount] = useState(0);

  // Map a transcript turnId to the nearest activity-timeline step turnId.
  // Many transcript turns have no corresponding step in the activity timeline;
  // walking backward through the transcript finds the closest preceding step.
  const activityTimeline = useStore((s) => jobId ? s.activityTimelines[jobId] : undefined);
  const transcript = useStore((s) => jobId ? s.transcript[jobId] : undefined);
  const stepTurnIdSet = useMemo(() => {
    if (!activityTimeline) return new Set<string>();
    return new Set(activityTimeline.activities.flatMap((a) => a.steps.map((s) => s.turnId)));
  }, [activityTimeline]);

  const mapToStepTurnId = useCallback((turnId: string | null): string | null => {
    if (!turnId || stepTurnIdSet.size === 0) return turnId;
    if (stepTurnIdSet.has(turnId)) return turnId;
    if (!transcript) return turnId;
    // Find the position of this turnId in the transcript, then walk backward
    const idx = transcript.findIndex((e) => e.turnId === turnId);
    if (idx < 0) return turnId;
    for (let i = idx - 1; i >= 0; i--) {
      const tid = transcript[i]?.turnId;
      if (tid && stepTurnIdSet.has(tid)) return tid;
    }
    // Fallback: walk forward
    for (let i = idx + 1; i < transcript.length; i++) {
      const tid = transcript[i]?.turnId;
      if (tid && stepTurnIdSet.has(tid)) return tid;
    }
    return turnId;
  }, [stepTurnIdSet, transcript]);

  // Map visible turnId from feed scroll position to the nearest activity step
  const visibleStepTurnId = useMemo(
    () => mapToStepTurnId(visibleTurnId),
    [visibleTurnId, mapToStepTurnId],
  );

  const resizeCleanupRef = useRef<(() => void) | null>(null);
  // Clean up sidebar resize listeners on unmount (prevents leak if nav away mid-resize)
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

  const tabBarRef = useRef<HTMLDivElement>(null);

  const handleTabChange = useCallback((v: string) => {
    setTab(v);
    if (v !== "diff") setStepFilter(null);
    if (v !== "live") setScrollToSeq(null);
    if (window.innerWidth < 768 && tabBarRef.current) {
      const main = tabBarRef.current.closest("main");
      if (main) {
        main.scrollTop = tabBarRef.current.offsetTop - main.offsetTop;
      }
    }
  }, []);

  // ── Mobile swipe-to-switch-tab ──
  const mobileTabOrder = useMemo(() => {
    const tabs = ["live", "shell", "diff", "files", "metrics"];
    if (hasArtifacts) tabs.push("artifacts");
    return tabs;
  }, [hasArtifacts]);
  const touchRef = useRef<{ x: number; y: number; t: number; el: EventTarget | null } | null>(null);
  const [slideDir, setSlideDir] = useState<"left" | "right" | null>(null);

  /** Walk from `el` up to `boundary` — return true if any ancestor scrolls horizontally. */
  const isInsideHScrollable = useCallback((el: EventTarget | null, boundary: HTMLElement) => {
    let node = el as HTMLElement | null;
    while (node && node !== boundary) {
      // Monaco uses .monaco-scrollable-element; also catch any generic overflow-x
      if (node.classList?.contains("monaco-scrollable-element") || node.classList?.contains("monaco-editor")) return true;
      if (node.scrollWidth > node.clientWidth + 1) {
        const ov = getComputedStyle(node).overflowX;
        if (ov === "auto" || ov === "scroll") return true;
      }
      node = node.parentElement;
    }
    return false;
  }, []);

  const onSwipeTouchStart = useCallback((e: React.TouchEvent) => {
    if (window.innerWidth >= 768) return;
    const touch = e.touches[0];
    if (!touch) return;
    touchRef.current = { x: touch.clientX, y: touch.clientY, t: Date.now(), el: e.target };
  }, []);
  const onSwipeTouchEnd = useCallback((e: React.TouchEvent) => {
    const start = touchRef.current;
    if (!start || window.innerWidth >= 768) return;
    touchRef.current = null;
    // If touch originated inside a horizontally scrollable element, don't hijack the swipe
    if (isInsideHScrollable(start.el, e.currentTarget as HTMLElement)) return;
    const touch = e.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    const dt = Date.now() - start.t;
    // Require: ≥60px horizontal, clearly horizontal (2:1 ratio), quick (<400ms)
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 2 || dt > 400) return;

    // Activity overlay: swipe right (dx>0) on Live opens it; swipe left (dx<0) when open closes it
    if (dx > 0 && tab === "live" && !mobileActivityOpen) {
      setMobileActivityOpen(true);
      return;
    }
    if (dx < 0 && mobileActivityOpen) {
      setMobileActivityOpen(false);
      return;
    }

    const idx = mobileTabOrder.indexOf(tab);
    if (idx === -1) return;
    const len = mobileTabOrder.length;
    // Swipe left (dx<0) = next tab; swipe right (dx>0) = previous tab
    // Carousel: wrap around at edges
    const nextIdx = dx < 0 ? (idx + 1) % len : (idx - 1 + len) % len;
    const nextTab = mobileTabOrder[nextIdx];
    if (!nextTab) return;
    setSlideDir(dx < 0 ? "right" : "left");
    handleTabChange(nextTab);
  }, [tab, mobileTabOrder, mobileActivityOpen, handleTabChange, isInsideHScrollable]);

  const handleViewStepChanges = useCallback((filePaths: string[], label: string, seq?: number, turnId?: string) => {
    setStepFilter({ filePaths, label, scrollToSeq: seq, turnId });
    setTab("diff");
  }, []);

  const handleClearStepFilter = useCallback(() => {
    setStepFilter(null);
  }, []);

  const handleNavigateToStep = useCallback((seq: number, turnId?: string) => {
    setScrollToSeq(seq);
    setTab("live");
    if (turnId) {
      setSelectedTurnId(mapToStepTurnId(turnId));
      setSearchActive(true);
    }
  }, [mapToStepTurnId]);

  useEffect(() => {
    if (!jobId) return;
    fetchArtifacts(jobId)
      .then((res) => {
        setHasArtifacts(res.items.length > 0);
        setArtifactCount(res.items.length);
      })
      .catch(() => {});
  }, [jobId, job?.state]);

  useEffect(() => {
    if (!hasArtifacts && tab === "artifacts") setTab("live");
  }, [hasArtifacts, tab]);

  // Open a new terminal session in the drawer, scoped to this job's worktree.
  // Each click intentionally creates a new session — multiple sessions per job are supported.
  const createTerminalSession = useStore((s) => s.createTerminalSession);
  const terminalSessions = useStore((s) => s.terminalSessions);
  const jobTerminalCount = Object.values(terminalSessions).filter((s) => s.jobId === jobId).length;

  const handleOpenJobTerminal = useCallback(() => {
    if (!job?.worktreePath || !jobId) return;
    const label = formatJobTerminalLabel(job, jobId);
    createTerminalSession({ cwd: job.worktreePath, label, jobId });
  }, [job, jobId, createTerminalSession]);

  // Open a job-scoped SSE connection for full event streaming (no suppression
  // even when >20 active jobs). Closed automatically when navigating away.
  useSSE(jobId);

  useEffect(() => {
    if (!loading) return;
    const timer = setTimeout(() => setShowSkeleton(true), SKELETON_DELAY_MS);
    return () => clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!jobId) { setLoading(false); return; }
    let cancelled = false;
    const existing = useStore.getState().jobs[jobId];
    if (existing) setLoading(false);
    fetchJob(jobId)
      .then((f) => {
        if (cancelled) return;
        useStore.setState((s) => ({ jobs: { ...s.jobs, [f.id]: enrichJob(f as JobSummary) } }));
      })
      .catch((err) => console.error("Failed to fetch job", err))
      .finally(() => {
        if (!cancelled && !existing) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Load historical transcript from the backend event store.
  // Logs are fetched directly by LogsPanel based on the active min-level.
  useEffect(() => {
    if (!jobId) return;
    fetchJobTranscript(jobId).then((transcript) => {
        useStore.setState((s) => {
          const existingTranscript = s.transcript[jobId] ?? [];
          const mergedTx = [
            ...transcript,
            ...existingTranscript.filter((e) => !transcript.some((ne) => ne.seq === e.seq)),
          ].sort((a, b) => a.seq - b.seq);
          return {
            transcript: { ...s.transcript, [jobId]: mergedTx },
          };
        });
    }).catch((err) => console.error("Failed to fetch job transcript", err));
  }, [jobId]);

  // Hydrate activity timeline from snapshot (turn summaries).
  useEffect(() => {
    if (!jobId) return;
    fetchJobSnapshot(jobId)
      .then((snapshot) => useStore.getState().hydrateJob(snapshot))
      .catch(() => { /* best-effort */ });
  }, [jobId]);

  // Load pending approvals so late-joining clients can approve/reject.
  useEffect(() => {
    if (!jobId) return;
    fetchApprovals(jobId).then((approvals) => {
      useStore.setState((s) => {
        const updated = { ...s.approvals };
        for (const a of approvals) updated[a.id] = a;
        return { approvals: updated };
      });
    }).catch((err) => console.error("Failed to fetch approvals", err));
  }, [jobId]);

  // Load diff data: on mount and when job state changes (e.g. reaches terminal state).
  const jobState = job?.state;
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    fetchJobDiff(jobId)
      .then((files) => {
        if (cancelled) return;
        useStore.setState((s) => ({
          diffs: { ...s.diffs, [jobId]: files },
        }));
      })
      .catch((err) => {
        if (!cancelled) console.error("Failed to fetch job diff", err);
      });
    return () => { cancelled = true; };
  }, [jobId, jobState]);

  const doCancelJob = useCallback(async () => {
    if (!jobId) return;
    try {
      const updated = await cancelJob(jobId);
      await archiveJob(jobId);
      useStore.setState((s) => ({
        jobs: { ...s.jobs, [updated.id]: { ...updated, archivedAt: new Date().toISOString() } },
      }));
      toast.success("Job canceled and cleaned up");
      navigate("/");
    } catch (e) { toast.error(String(e)); }
  }, [jobId, navigate]);

  const handleResume = useCallback(async () => {
    if (!jobId) return;
    setActionLoading(true);
    try {
      const result = await resumeJob(jobId);
      useStore.setState((state) => {
        const existing = state.jobs[jobId];
        if (!existing) return state;
        return {
          ...state,
          jobs: {
            ...state.jobs,
            [jobId]: {
              ...existing,
              state: result.state,
              branch: result.branch,
              worktreePath: result.worktreePath,
              updatedAt: result.updatedAt,
              completedAt: null,
              archivedAt: null,
            },
          },
        };
      });
      toast.success(`Resumed: ${result.id}`);
      navigate(`/jobs/${jobId}`);
    } catch (e) { toast.error(String(e)); }
    finally { setActionLoading(false); }
  }, [jobId, navigate]);

  const doDiscardJob = useCallback(async (toastMsg: string) => {
    if (!jobId) return;
    try {
      await resolveJob(jobId, "discard");
      await archiveJob(jobId);
      useStore.setState((s) => {
        const existing = s.jobs[jobId];
        if (!existing) return s;
        return { jobs: { ...s.jobs, [jobId]: { ...existing, resolution: "discarded", archivedAt: new Date().toISOString() } } };
      });
      toast.success(toastMsg);
      navigate("/");
    } catch (e) { toast.error(String(e)); }
  }, [jobId, navigate]);

  const handleResolve = useCallback(async (action: "merge" | "smart_merge" | "create_pr" | "agent_merge") => {
    if (!jobId) return;
    setResolveLoading(action);
    try {
      const res = await resolveJob(jobId, action);
      const refreshedJob = action === "agent_merge"
        ? null
        : await fetchJob(jobId).catch(() => null);
      const refreshedSummary = refreshedJob
        ? enrichJob(refreshedJob as JobSummary)
        : null;
      const conflictLike =
        res.resolution === "conflict" ||
        (refreshedSummary?.mergeStatus ?? null) === "conflict" ||
        ((res.conflictFiles?.length ?? 0) > 0) ||
        ((refreshedSummary?.conflictFiles?.length ?? 0) > 0);
      useStore.setState((s) => {
        const existing = s.jobs[jobId];
        const baseJob = refreshedSummary ?? existing;
        if (!baseJob) return {};
        const nextJob = action === "agent_merge"
          ? {
              ...baseJob,
              state: "running",
              resolution: null,
              archivedAt: null,
              conflictFiles: res.conflictFiles ?? baseJob.conflictFiles,
              resolutionError: null,
            }
          : {
              ...baseJob,
              resolution: res.resolution,
              prUrl: res.prUrl ?? baseJob.prUrl,
              conflictFiles: res.conflictFiles ?? baseJob.conflictFiles,
              resolutionError: res.resolution === "unresolved" ? (res.error ?? null) : null,
              mergeStatus:
                res.resolution === "merged"
                  ? "merged"
                  : res.resolution === "conflict"
                    ? "conflict"
                    : baseJob.mergeStatus,
            };
        return {
          jobs: {
            ...s.jobs,
            [jobId]: nextJob,
          },
        };
      });
      if (res.prUrl) {
        toast.success("PR created", {
          description: res.prUrl,
          action: { label: "Open", onClick: () => window.open(res.prUrl!, "_blank") },
        });
      } else if (action === "agent_merge") {
        toast.success("Resolving with agent…");
      } else if (res.resolution === "merged") {
        toast.success("Merged");
      } else if (res.resolution === "pr_created") {
        toast.success("PR created");
      } else if (conflictLike) {
        toast.error("Merge conflict detected");
      } else {
        toast.error(res.error ?? "Merge did not complete");
      }
    } catch (e) { toast.error(String(e)); }
    finally { setResolveLoading(null); }
  }, [jobId]);

  if (!jobId) return null;

  if (loading && showSkeleton) return <JobDetailSkeleton />;
  if (loading) return null;

  if (!job) {
    return (
      <div className="flex flex-col items-center gap-3 py-16">
        <p className="text-muted-foreground">Job not found</p>
        <Button variant="ghost" onClick={() => navigate("/")}>
          <ArrowLeft size={16} />
          Back to Dashboard
        </Button>
      </div>
    );
  }

  const canCancel = ["preparing", "queued", "running", "waiting_for_approval"].includes(job.state);
  const canResume = job.state === "failed";
  const isRunning = job.state === "running";
  const isPreparing = job.state === "preparing";

  const hasMergeConflict =
    !["merged", "pr_created", "discarded"].includes(job.resolution ?? "") &&
    (job.resolution === "conflict" ||
    job.mergeStatus === "conflict" ||
    ((job.conflictFiles?.length ?? 0) > 0));
  const unresolvedResolutionError =
    !hasMergeConflict && (job.resolution === "unresolved" || !job.resolution)
      ? (job.resolutionError ?? null)
      : null;
  const needsResolution =
    job.state === "review" &&
    (job.resolution === "unresolved" || job.resolution === "conflict" || !job.resolution);
  const isResolved =
    job.state === "completed" &&
    !!job.resolution &&
    job.resolution !== "unresolved" &&
    job.resolution !== "conflict";
  const canArchive = (job.state === "failed" || job.state === "canceled" || (job.state === "completed" && !isResolved)) && !job.archivedAt;

  return (
    <div className="px-0 md:flex md:flex-col md:h-full md:min-h-0">
      {/* ── Mobile compact status rail (< 768px) ── */}
      <div className="flex md:hidden items-center gap-2 h-10 px-2 border-b border-border bg-card shrink-0">
        <button onClick={() => navigate("/")} className="p-1.5 -ml-1 text-muted-foreground hover:text-foreground transition-colors" aria-label="Back to dashboard">
          <ArrowLeft size={16} />
        </button>
        <button
          onClick={() => setMobileDetailOpen(true)}
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
                  onClick={() => setCancelOpen(true)}
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-destructive transition-colors hover:bg-accent"
                >
                  <XCircle size={13} /> Cancel Job
                </button>
              )}
              {canResume && (
                <button
                  onClick={handleResume}
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <RotateCcw size={13} /> Resume
                </button>
              )}
              {hasWorktree && (
                <button
                  onClick={handleOpenJobTerminal}
                  className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <TerminalSquare size={13} /> Terminal
                  {jobTerminalCount > 0 && <span className="ml-auto text-[10px] font-semibold text-primary">×{jobTerminalCount}</span>}
                </button>
              )}
              <button
                onClick={() => setMobileDetailOpen(true)}
                className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                <FolderGit2 size={13} /> Job Details
              </button>
            </PopoverPrimitive.Content>
          </PopoverPrimitive.Portal>
        </PopoverPrimitive.Root>
      </div>

      {/* ── Mobile job detail bottom sheet ── */}
      <BottomSheet open={mobileDetailOpen} onClose={() => setMobileDetailOpen(false)} title="Job Details">
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
          <div className="flex flex-wrap gap-2 pt-2 border-t border-border">
            {canCancel && (
              <Button size="sm" variant="outline" className="text-destructive border-destructive/40" onClick={() => { setMobileDetailOpen(false); setCancelOpen(true); }}>
                <XCircle size={14} /> Cancel
              </Button>
            )}
            {canResume && (
              <Button size="sm" variant="outline" loading={actionLoading} onClick={() => { setMobileDetailOpen(false); handleResume(); }}>
                <RotateCcw size={14} /> Resume
              </Button>
            )}
            {needsResolution && hasChanges && (
              <>
                {!hasMergeConflict && (
                  <Button size="sm" variant="outline" className="gap-1" loading={resolveLoading === "smart_merge"} disabled={resolveLoading !== null} onClick={() => { setMobileDetailOpen(false); handleResolve("smart_merge"); }}>
                    <GitMerge size={14} /> Merge
                  </Button>
                )}
                {hasMergeConflict && (
                  <Button size="sm" variant="outline" className="gap-1" loading={resolveLoading === "agent_merge"} disabled={resolveLoading !== null} onClick={() => { setMobileDetailOpen(false); handleResolve("agent_merge"); }}>
                    <GitMerge size={14} /> Resolve with Agent
                  </Button>
                )}
                <Button size="sm" variant="outline" className="gap-1" loading={resolveLoading === "create_pr"} disabled={resolveLoading !== null} onClick={() => { setMobileDetailOpen(false); handleResolve("create_pr"); }}>
                  <GitPullRequest size={14} /> Create PR
                </Button>
                <Button size="sm" variant="outline" className="gap-1 text-destructive border-destructive/40" onClick={() => { setMobileDetailOpen(false); setDiscardOpen(true); }}>
                  <Trash2 size={14} /> Discard
                </Button>
              </>
            )}
            {needsResolution && !hasChanges && (
              <Button size="sm" variant="outline" className="gap-1" onClick={() => { setMobileDetailOpen(false); setMarkDoneOpen(true); }}>
                <CheckCircle2 size={14} /> Mark Done
              </Button>
            )}
            {isResolved && !job.archivedAt && (
              <Button size="sm" variant="outline" className="gap-1 text-green-600 border-green-500/40" onClick={() => { setMobileDetailOpen(false); setCompleteOpen(true); }}>
                <CheckCircle2 size={14} /> Complete & Archive
              </Button>
            )}
            {canArchive && (
              <Button size="sm" variant="outline" className="gap-1" onClick={() => { setMobileDetailOpen(false); setCompleteOpen(true); }}>
                <Archive size={14} /> {job.state === "failed" ? "Abandon" : "Archive"}
              </Button>
            )}
          </div>
        </div>
      </BottomSheet>

      {/* ── Desktop back button (hidden on mobile) ── */}
      <Button variant="ghost" size="sm" onClick={() => navigate("/")} className="mb-2 hidden md:inline-flex md:shrink-0">
        <ArrowLeft size={14} />
        Dashboard
      </Button>

      {/* Job header — hidden on mobile (rail + bottom sheet replaces it) */}
      <div className="hidden md:block md:shrink-0 rounded-lg border border-border bg-card p-4 mb-3">
        <div className="mb-2">
          {job.title ? (
            <h1 className="text-lg font-bold text-foreground break-words">{job.title}</h1>
          ) : (
            <h1 className="text-lg font-bold text-foreground break-words">{job.id}</h1>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-muted-foreground font-mono">{job.id}</span>
            <span aria-live="polite"><StateBadge state={job.state} /></span>
            <SdkBadge sdk={job.sdk} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canCancel && (
              <Button
                size="sm"
                variant="outline"
                className="text-destructive border-destructive/40 hover:bg-destructive/10"
                onClick={() => setCancelOpen(true)}
              >
                <XCircle size={14} />
                Cancel
              </Button>
            )}
            {canResume && (
              <Button size="sm" variant="outline" loading={actionLoading} onClick={handleResume}>
                <RotateCcw size={14} />
                Resume
              </Button>
            )}
            {needsResolution && hasChanges && (
              <>
                {!hasMergeConflict && (
                  <Tooltip content="Ask the agent to merge changes onto the base branch">
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1"
                      loading={resolveLoading === "smart_merge"}
                      disabled={resolveLoading !== null}
                      onClick={() => handleResolve("smart_merge")}
                    >
                      <GitMerge size={14} />
                      Merge
                    </Button>
                  </Tooltip>
                )}
                {hasMergeConflict && (
                  <Tooltip content="Ask the agent to resolve the merge conflict">
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1"
                      loading={resolveLoading === "agent_merge"}
                      disabled={resolveLoading !== null}
                      onClick={() => handleResolve("agent_merge")}
                    >
                      <GitMerge size={14} />
                      Resolve with Agent
                    </Button>
                  </Tooltip>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1"
                  loading={resolveLoading === "create_pr"}
                  disabled={resolveLoading !== null}
                  onClick={() => handleResolve("create_pr")}
                >
                  <GitPullRequest size={14} />
                  Create PR
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1 text-destructive border-destructive/40 hover:bg-destructive/10"
                  onClick={() => setDiscardOpen(true)}
                >
                  <Trash2 size={14} />
                  Discard
                </Button>
              </>
            )}
            {needsResolution && !hasChanges && (
              <Button
                size="sm"
                variant="outline"
                className="gap-1"
                onClick={() => setMarkDoneOpen(true)}
              >
                <CheckCircle2 size={14} />
                Mark Done
              </Button>
            )}
            {isResolved && !job.archivedAt && (
              <Button
                size="sm"
                variant="outline"
                className="gap-1 text-green-600 border-green-500/40 hover:bg-green-500/10"
                onClick={() => setCompleteOpen(true)}
              >
                <CheckCircle2 size={14} />
                Complete & Archive
              </Button>
            )}
            {canArchive && (
              <Button
                size="sm"
                variant="outline"
                className="gap-1"
                onClick={() => setCompleteOpen(true)}
              >
                <Archive size={14} />
                {job.state === "failed" ? "Abandon" : "Archive"}
              </Button>
            )}
            {/* Share disabled — read-only view not useful yet
            <Button
              size="sm"
              variant="outline"
              className="gap-1"
              onClick={async () => {
                try {
                  const { url } = await createShareLink(job.id);
                  await navigator.clipboard.writeText(url);
                  toast.success("Share link copied to clipboard");
                } catch {
                  toast.error("Failed to create share link");
                }
              }}
            >
              <Share2 size={14} />
              Share
            </Button>
            */}
          </div>
        </div>

        <div className="flex items-center gap-1.5 mb-3">
          <FolderGit2 size={13} className="text-muted-foreground/70 shrink-0" />
          <span className="text-sm text-muted-foreground font-mono">{job.repo.split("/").pop() ?? job.repo}</span>
        </div>

        {job.progressHeadline && ["running", "agent_running", "queued"].includes(job.state) && (
          <p className="text-sm italic text-primary/70 mb-3">{job.progressHeadline}</p>
        )}

        {isPreparing && (
          <div className="flex items-center gap-2 text-sm text-violet-400 animate-pulse mb-3">
            <Loader2 size={14} className="animate-spin" />
            {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up workspace…"}
          </div>
        )}

        {(job.description || job.prompt) && (
          <p className="text-sm text-muted-foreground mb-3 line-clamp-3">{job.description ?? job.prompt}</p>
        )}

        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-6 gap-y-2 text-sm mb-3">
          {[
            ["Branch", job.branch ?? "—"],
            ["Base", job.baseRef],
            ["Worktree", job.worktreePath ? job.worktreePath.split("/").pop() ?? job.worktreePath : "—"],
            ...(job.model ? [["Model", job.model]] : []),
            ...(job.sdk ? [["SDK", job.sdk]] : []),
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
          <a
            href={job.prUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
          >
            <ExternalLink size={14} />
            View Pull Request
          </a>
        )}

        {/* Model downgrade banner */}
        {job.modelDowngraded && (
          <div className="flex items-start gap-2 mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
            <ArrowDownCircle size={16} className="text-amber-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-amber-500">Model downgraded</p>
              <p className="text-sm text-amber-400 mt-0.5">
                Requested <span className="font-semibold">{job.requestedModel}</span> but the SDK served <span className="font-semibold">{job.actualModel}</span>.
                The job was stopped before the agent could proceed with the wrong model.
              </p>
              <p className="text-xs text-amber-400/70 mt-1">
                You can discard this job, create a PR with any partial changes, or resume with additional instructions.
              </p>
            </div>
          </div>
        )}

        {/* Failure banner */}
        {job.state === "failed" && (
          <div className="flex items-start gap-2 mt-3 rounded-md border border-red-500/30 bg-red-500/10 p-3">
            <XCircle size={16} className="text-red-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-500">Job failed</p>
              <p className="text-sm text-red-400 mt-0.5">{job.failureReason ?? "No additional details available"}</p>
            </div>
          </div>
        )}

        {/* Review banner */}
        {job.state === "review" && (() => {
          const isConflict = hasMergeConflict;
          const isSignOff = job.resolution === "unresolved" || !job.resolution;
          return (
            <div className={`mt-3 rounded-md border p-3 ${isConflict ? "border-amber-500/30 bg-amber-500/10" : isSignOff ? "border-blue-500/30 bg-blue-500/10" : "border-green-500/30 bg-green-500/10"}`}>
              <div className="flex items-start gap-2">
                {isConflict ? (
                  <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                ) : isSignOff ? (
                  <GitMerge size={16} className="text-blue-500 shrink-0 mt-0.5" />
                ) : (
                  <CheckCircle2 size={16} className="text-green-500 shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={`text-sm font-medium ${isConflict ? "text-amber-500" : isSignOff ? "text-blue-500" : "text-green-500"}`}>
                    {isConflict ? "Merge conflict — user input required" : isSignOff ? "Review required" : "Ready for resolution"}
                  </p>
                  <p className={`text-sm mt-0.5 ${isConflict ? "text-amber-400" : isSignOff ? "text-blue-400" : "text-green-400"}`}>
                    {isConflict
                      ? "Merge conflict detected. Resolve with the agent, create a PR to fix manually, or discard."
                      : null}
                    {!isConflict && isSignOff && (
                      hasChanges
                        ? "Choose how to handle the changes: auto merge onto the main worktree, create a PR, or discard."
                        : "Completed with no changes to merge."
                    )}
                  </p>
                  {unresolvedResolutionError && (
                    <p className="text-sm mt-1 text-blue-300/90">
                      Automatic merge failed: {unresolvedResolutionError}
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {/* Completed banner */}
        {job.state === "completed" && (
          <div className="mt-3 rounded-md border border-green-500/30 bg-green-500/10 p-3">
            <div className="flex items-start gap-2">
              <CheckCircle2 size={16} className="text-green-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-green-500">Job completed</p>
                <p className="text-sm mt-0.5 text-green-400">
                  {job.resolution === "merged" ? "Changes merged into base branch."
                    : job.resolution === "pr_created" ? "Pull request created."
                    : job.resolution === "discarded" ? (hasChanges ? "Changes discarded." : "Completed — no changes to merge.")
                    : null}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Canceled banner */}
        {job.state === "canceled" && (
          <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
              <p className="text-sm font-medium text-amber-500">Job canceled</p>
            </div>
          </div>
        )}
      </div>

      {completeOpen && job && (
        <CompleteJobDialog job={job} open onClose={() => setCompleteOpen(false)} onArchived={() => navigate("/")} />
      )}

      {/* Tab bar — desktop shows all tabs + terminal button; mobile shows scrollable strip */}
      <Tabs value={tab} onValueChange={handleTabChange} className="md:mb-2 md:shrink-0" ref={tabBarRef}>
        {/* Desktop layout (hidden on mobile) */}
        <div className="hidden md:flex items-center gap-2">
          <TabsList className="overflow-x-auto">
            <TabsTrigger value="live">Live</TabsTrigger>
            <TabsTrigger value="shell"><TerminalSquare size={13} className="mr-1.5" />Shell</TabsTrigger>
            <TabsTrigger value="files"><FolderTree size={13} className="mr-1.5" />Files</TabsTrigger>
            {hasChanges && <TabsTrigger value="diff"><GitBranch size={13} className="mr-1.5" />Changes</TabsTrigger>}
            <TabsTrigger value="metrics"><BarChart3 size={13} className="mr-1.5" />Metrics</TabsTrigger>
            {hasArtifacts && (
              <TabsTrigger value="artifacts">
                Artifacts
                {artifactCount > 0 && (
                  <span className="ml-1.5 text-[10px] leading-none bg-muted text-muted-foreground rounded-full px-1.5 py-0.5 font-normal">
                    {artifactCount}
                  </span>
                )}
              </TabsTrigger>
            )}
          </TabsList>

          {hasWorktree && (
            <Tooltip content={jobTerminalCount > 0 ? `Open new terminal (${jobTerminalCount} open)` : "Open terminal in worktree"}>
              <button
                onClick={handleOpenJobTerminal}
                className="flex items-center gap-1.5 px-2.5 h-9 rounded-md border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors shrink-0"
              >
                <TerminalSquare size={13} />
                <span>Terminal</span>
                {jobTerminalCount > 0 && (
                  <span className="ml-0.5 text-[10px] font-semibold text-primary">×{jobTerminalCount}</span>
                )}
              </button>
            </Tooltip>
          )}

          {/* Activity toggle — visible at md–lg where the sidebar is hidden */}
          <Tooltip content="Toggle activity timeline">
            <button
              onClick={() => setMobileActivityOpen((o) => !o)}
              className={cn(
                "hidden md:flex lg:hidden items-center gap-1.5 px-2.5 h-9 rounded-md border border-border text-xs font-medium transition-colors shrink-0",
                mobileActivityOpen ? "text-primary border-primary/40 bg-primary/10" : "text-muted-foreground hover:text-foreground hover:bg-accent",
              )}
            >
              <ListTree size={13} />
              <span>Activity</span>
            </button>
          </Tooltip>

        </div>
      </Tabs>

      {/* Tab content — full-bleed on mobile, min-height on desktop */}
      <div
        className={cn(
          "min-h-0 pb-[52px] md:pb-0 md:flex-1 md:flex md:flex-col md:overflow-hidden",
          slideDir === "left" && "animate-slide-left",
          slideDir === "right" && "animate-slide-right",
        )}
        onTouchStart={onSwipeTouchStart}
        onTouchEnd={onSwipeTouchEnd}
        onAnimationEnd={() => setSlideDir(null)}
      >
      {tab === "live" && (
        <div className="flex flex-row relative md:h-full md:min-h-0">
          {/* Activity overlay — slides in from left (available below lg where sidebar is hidden) */}
          {mobileActivityOpen && (
            <div className="lg:hidden absolute inset-0 z-30 flex">
              <div className="w-[85%] max-w-xs h-full bg-card border-r border-border shadow-xl animate-slide-left overflow-hidden">
                <button
                  onClick={() => setMobileActivityOpen(false)}
                  className="flex items-center gap-2 px-4 py-2.5 w-full text-left border-b border-border hover:bg-accent/50 transition-colors"
                >
                  <PanelLeftClose size={13} className="text-muted-foreground shrink-0" />
                  <span className="text-sm font-semibold text-muted-foreground">Activity</span>
                </button>
                <div className="flex-1 overflow-hidden" style={{ height: 'calc(100% - 41px)' }}>
                  <ActivityTimeline
                    jobId={jobId}
                    jobState={job.state}
                    onStepClick={(turnId) => {
                      setMobileActivityOpen(false);
                      setScrollToTurnId(turnId);
                      setSelectedTurnId(turnId);
                    }}
                    selectedTurnId={selectedTurnId}
                    searchActive={searchActive}
                    visibleStepTurnId={visibleStepTurnId}
                  />
                </div>
              </div>
              <div className="flex-1 bg-black/40" onClick={() => setMobileActivityOpen(false)} />
            </div>
          )}
          {/* Activity Timeline sidebar — hidden on small screens */}
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
                <div className="flex-1 overflow-hidden">
                  <ActivityTimeline
                    jobId={jobId}
                    jobState={job.state}
                    onStepClick={(turnId) => {
                      setScrollToTurnId(turnId);
                      setSelectedTurnId(turnId);
                    }}
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
          <div className="flex flex-col gap-4 flex-1 min-w-0 lg:pl-2">
            <div className="h-[calc(100dvh-92px)] md:h-full min-h-[22rem]">
              <CuratedFeed
                jobId={jobId}
                sdk={job.sdk}
                interactive
                jobState={job.state}
                pausable={isRunning}
                prompt={job.prompt}
                promptTimestamp={job.createdAt}
                onViewStepChanges={handleViewStepChanges}
                onSearchHighlight={(turnId) => {
                  setSelectedTurnId(turnId ? mapToStepTurnId(turnId) : null);
                  setSearchActive(turnId !== null);
                }}
                onVisibleTurnId={setVisibleTurnId}
                visibleStepTurnId={visibleStepTurnId}
                scrollToSeq={scrollToSeq}
                scrollToTurnId={scrollToTurnId}
              />
            </div>
          </div>
        </div>
      )}



      {tab === "files" && (
        <TabErrorBoundary>
          <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
            <WorkspaceBrowser jobId={jobId} />
          </Suspense>
        </TabErrorBoundary>
      )}

      {tab === "diff" && (
        <TabErrorBoundary>
          <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
            <DiffViewer
            jobId={jobId}
            jobState={job.state}
            resolution={job.resolution}
            archivedAt={job.archivedAt}
            onAskSent={() => setTab("live")}
            stepFilter={stepFilter}
            onClearStepFilter={handleClearStepFilter}
            onNavigateToStep={handleNavigateToStep}
          />
          </Suspense>
        </TabErrorBoundary>
      )}

      {tab === "metrics" && (
        <MetricsPanel jobId={jobId} isRunning={isRunning} />
      )}

      {tab === "shell" && (
        <TabErrorBoundary>
          <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
            <div className="md:h-full h-[60dvh] rounded-lg overflow-hidden border border-border">
              <AgentTerminal jobId={jobId} isRunning={isRunning} />
            </div>
          </Suspense>
        </TabErrorBoundary>
      )}



      {tab === "artifacts" && (
        <TabErrorBoundary>
          <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
            <ArtifactViewer jobId={jobId} onCountChange={(n) => { setArtifactCount(n); setHasArtifacts(n > 0); }} />
          </Suspense>
        </TabErrorBoundary>
      )}
      </div>{/* end tab content min-height wrapper */}

      {/* ── Mobile contextual footer — shows review actions above the bottom tab bar ── */}
      {needsResolution && hasChanges && tab === "diff" && (
        <div className="fixed bottom-[52px] inset-x-0 z-40 flex md:hidden items-center justify-center gap-2 px-3 py-2 border-t border-border bg-card/95 backdrop-blur-sm">
          {!hasMergeConflict && (
            <Button size="sm" className="flex-1 gap-1" loading={resolveLoading === "smart_merge"} disabled={resolveLoading !== null} onClick={() => handleResolve("smart_merge")}>
              <GitMerge size={14} /> Merge
            </Button>
          )}
          {hasMergeConflict && (
            <Button size="sm" className="flex-1 gap-1" loading={resolveLoading === "agent_merge"} disabled={resolveLoading !== null} onClick={() => handleResolve("agent_merge")}>
              <GitMerge size={14} /> Resolve
            </Button>
          )}
          <Button size="sm" variant="outline" className="flex-1 gap-1" loading={resolveLoading === "create_pr"} disabled={resolveLoading !== null} onClick={() => handleResolve("create_pr")}>
            <GitPullRequest size={14} /> PR
          </Button>
          <Button size="sm" variant="outline" className="gap-1 text-destructive border-destructive/40" onClick={() => setDiscardOpen(true)}>
            <Trash2 size={14} />
          </Button>
        </div>
      )}

      {/* ── Mobile bottom tab bar (iOS-style) — max 5 primary + More overflow ── */}
      <nav className="fixed bottom-0 inset-x-0 z-50 md:hidden flex items-end justify-around border-t border-border bg-card/95 backdrop-blur-sm safe-area-pb landscape:items-center" style={{ height: 52 }}>
        {/* Activity toggle — visually distinct (opens overlay, not a tab) */}
        <button
          onClick={() => { if (tab !== "live") handleTabChange("live"); setMobileActivityOpen((o) => !o); setMobileMoreOpen(false); }}
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
        {/* More overflow — Metrics, Artifacts */}
        <div className="relative flex-1 min-w-0">
          <button
            onClick={() => setMobileMoreOpen((o) => !o)}
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

      <ConfirmDialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={doCancelJob}
        title="Cancel & Clean Up?"
        description="This will stop the running agent, archive the job, and remove the worktree and branch."
        confirmLabel="Cancel & Clean Up"
      />

      <ConfirmDialog
        open={discardOpen}
        onClose={() => setDiscardOpen(false)}
        onConfirm={() => doDiscardJob("Changes discarded and cleaned up")}
        title="Discard & Clean Up?"
        description="All changes in the worktree will be deleted and the job will be archived. This cannot be undone."
        confirmLabel="Discard & Clean Up"
      />

      <ConfirmDialog
        open={markDoneOpen}
        onClose={() => setMarkDoneOpen(false)}
        onConfirm={() => doDiscardJob("Job completed and archived")}
        title="Mark as Done?"
        description="The job will be marked as complete and archived. The worktree and branch will be cleaned up."
        confirmLabel="Mark Done & Archive"
      />

    </div>
  );
}
