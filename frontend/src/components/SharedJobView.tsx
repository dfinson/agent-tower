/**
 * Read-only shared job view — accessed via /shared/:token.
 *
 * Fetches a full snapshot through the share token, hydrates the Zustand
 * store, and reuses the same rich components (CuratedFeed, DiffViewer)
 * as the main job detail screen — in read-only mode.
 */

import { useEffect, useState, useRef, useCallback, Suspense, Component, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useStore, enrichJob } from "../store";
import type { JobSummary } from "../store";
import { fetchSharedSnapshot } from "../api/client";
import { CuratedFeed } from "./CuratedFeed";
import { ActivityTimeline } from "./ActivityTimeline";
import { StateBadge } from "./StateBadge";
import { SdkBadge } from "./SdkBadge";
import { Spinner } from "./ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";
import { cn } from "../lib/utils";
import { lazyRetry } from "../lib/lazyRetry";
import { GitBranch, PanelLeftClose, PanelLeftOpen } from "lucide-react";

const DiffViewer = lazyRetry(() => import("./DiffViewer"));

const BASE = "/api";

/** Terminal job states where the agent is no longer working. */
const TERMINAL_STATES = new Set(["review", "completed", "failed", "canceled", "archived"]);

/** Min sidebar width for the activity timeline drag-resize. */
const MIN_SIDEBAR_W = 160;
const MAX_SIDEBAR_W = 480;
const DEFAULT_SIDEBAR_W = 260;

/** Error boundary for lazy-loaded tabs. */
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

export function SharedJobView() {
  const { token } = useParams<{ token: string }>();
  const [job, setJob] = useState<JobSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("live");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_W);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [scrollToTurnId, setScrollToTurnId] = useState<string | null>(null);
  const sidebarResizing = useRef(false);

  // Fetch snapshot and hydrate store
  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    fetchSharedSnapshot(token)
      .then((snapshot) => {
        if (cancelled) return;
        useStore.getState().hydrateJob(snapshot);
        setJob(enrichJob(snapshot.job));
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e.status === 404 ? "Share link expired or invalid" : "Failed to load shared job");
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [token]);

  // SSE for live updates via share endpoint
  useEffect(() => {
    if (!token || !job) return;
    const { dispatchSSEEvent } = useStore.getState();

    const es = new EventSource(`${BASE}/share/${encodeURIComponent(token)}/events`);

    const eventTypes = [
      "job_state_changed", "log_line", "transcript_update", "diff_update",
      "approval_requested", "approval_resolved", "session_heartbeat",
      "snapshot", "job_review", "job_completed", "job_failed", "job_resolved",
      "job_archived", "session_resumed", "job_title_updated", "model_downgraded",
      "tool_group_summary", "merge_completed", "merge_conflict",
      "telemetry_updated", "plan_step_updated", "turn_summary",
    ];

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (ev: MessageEvent) => {
        try {
          const data: unknown = JSON.parse(ev.data as string);
          setTimeout(() => dispatchSSEEvent(eventType, data), 0);
        } catch { /* ignore */ }
      });
    }

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setError("Connection lost — share link may have expired");
      }
    };

    return () => es.close();
  }, [token, job?.id]);

  // Keep local job state in sync with store updates
  const storeJob = useStore((s) => job ? s.jobs[job.id] : undefined);
  useEffect(() => {
    if (storeJob) setJob(storeJob);
  }, [storeJob]);

  // Sidebar resize handler
  const handleSidebarResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    sidebarResizing.current = true;
    const startX = e.clientX;
    const startW = sidebarWidth;
    const onMove = (ev: MouseEvent) => {
      if (!sidebarResizing.current) return;
      const newW = Math.min(MAX_SIDEBAR_W, Math.max(MIN_SIDEBAR_W, startW + ev.clientX - startX));
      setSidebarWidth(newW);
    };
    const onUp = () => {
      sidebarResizing.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [sidebarWidth]);

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-20 text-center">
        <h1 className="text-xl font-bold text-destructive mb-2">Share link unavailable</h1>
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (loading || !job) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  const isRunning = !TERMINAL_STATES.has(job.state);

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-2">
        <ol className="flex items-center gap-2 text-xs text-muted-foreground">
          <li>CodePlane</li>
          <li aria-hidden="true" className="text-muted-foreground/50">/</li>
          <li aria-current="page">Shared View</li>
        </ol>
      </nav>

      {/* Job header */}
      <div className="rounded-lg border border-border bg-card p-5 mb-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2 min-w-0">
            <h1 className="text-lg font-bold text-foreground break-words">
              {job.title || job.id}
            </h1>
            {job.sdk && <SdkBadge sdk={job.sdk} />}
          </div>
          <span aria-live="polite"><StateBadge state={job.state} /></span>
        </div>

        {job.progressHeadline && isRunning && (
          <p className="text-sm italic text-primary/70 mb-3">{job.progressHeadline}</p>
        )}

        {(job.description || job.prompt) && (
          <p className="text-sm text-muted-foreground mb-3">{job.description ?? job.prompt}</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-x-6 gap-y-2 text-sm">
          {[
            ["Branch", job.branch ?? "\u2014"],
            ["Base", job.baseRef],
            ...(job.model ? [["Model", job.model]] : []),
            ["Created", new Date(job.createdAt).toLocaleString()],
            ...(job.completedAt ? [["Completed", new Date(job.completedAt).toLocaleString()]] : []),
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-[11px] sm:text-xs text-muted-foreground uppercase font-semibold tracking-wide">{label}</p>
              <p className="text-sm break-all">{value}</p>
            </div>
          ))}
        </div>

        {job.failureReason && (
          <div className="mt-3 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2">
            <p className="text-sm text-destructive whitespace-pre-wrap break-words max-h-[200px] overflow-y-auto">{job.failureReason}</p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab} className="mb-4">
        <TabsList>
          <TabsTrigger value="live">Live</TabsTrigger>
          <TabsTrigger value="diff"><GitBranch size={13} className="mr-1.5" />Changes</TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Tab content */}
      <div className="min-h-[80dvh]">
        {tab === "live" && (
          <div className="flex flex-row">
            {/* Activity Timeline sidebar */}
            <div
              className={cn(
                "hidden lg:flex flex-col flex-shrink-0 h-[80dvh] min-h-[22rem] rounded-lg border border-border bg-card overflow-hidden",
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
                      jobId={job.id}
                      jobState={job.state}
                      onStepClick={(turnId) => {
                        setScrollToTurnId(turnId);
                        setSelectedTurnId(turnId);
                      }}
                      selectedTurnId={selectedTurnId}
                    />
                  </div>
                </>
              )}
            </div>
            {/* Drag handle */}
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
              <div className="h-[80dvh] min-h-[22rem]">
                <CuratedFeed
                  jobId={job.id}
                  sdk={job.sdk}
                  interactive={false}
                  jobState={job.state}
                  prompt={job.prompt}
                  promptTimestamp={job.createdAt}
                  scrollToTurnId={scrollToTurnId}
                />
              </div>
            </div>
          </div>
        )}

        {tab === "diff" && (
          <TabErrorBoundary>
            <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
              <DiffViewer
                jobId={job.id}
                jobState={job.state}
              />
            </Suspense>
          </TabErrorBoundary>
        )}
      </div>
    </div>
  );
}
