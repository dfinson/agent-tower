/**
 * ReviewDashboard — orchestrator for the Review tab.
 *
 * Sub-views:
 * - Changes: code diff viewer (was a top-level tab)
 * - Timeline: per-session structural changes (hidden for single-session jobs)
 * - Story: structured review story with verdict
 *
 * Degradation: when CodeRecon is unavailable (available=false on multi-session),
 * the Story sub-view becomes default. Timeline hidden.
 */
import { Suspense, useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { fetchMultiSession } from "../api/client";
import { useStore } from "../store";
import { selectMultiSession } from "../store/selectors";
import { Spinner } from "./ui/spinner";
import { ReviewSubTabs, type ReviewSubView } from "./review/ReviewSubTabs";
import { TimelineSubView } from "./review/TimelineSubView";
import { StorySubView } from "./review/StorySubView";
import { lazyRetry } from "../lib/lazyRetry";
import type { StepFilter } from "./DiffViewer";

const DiffViewer = lazyRetry(() => import("./DiffViewer"));

// -- Main Component --

interface ReviewDashboardProps {
  jobId: string;
  hasChanges?: boolean;
  jobState?: string;
  resolution?: string | null;
  archivedAt?: string | null;
  onAskSent?: () => void;
  stepFilter?: StepFilter | null;
  onClearStepFilter?: () => void;
  onNavigateToStep?: (seq: number, turnId?: string) => void;
  /** Externally-requested sub-view (e.g. navigating to changes from activity feed) */
  requestedSubView?: ReviewSubView | null;
  onSubViewHandled?: () => void;
}

export function ReviewDashboard({
  jobId,
  hasChanges,
  jobState,
  resolution,
  archivedAt,
  onAskSent,
  stepFilter,
  onClearStepFilter,
  onNavigateToStep,
  requestedSubView,
  onSubViewHandled,
}: ReviewDashboardProps) {
  // Read from store (may already be prefetched via SSE side-effect)
  const cachedMulti = useStore(selectMultiSession(jobId));
  const setMultiSession = useStore((s) => s.setMultiSession);

  const [loading, setLoading] = useState(cachedMulti == null);
  const [error, setError] = useState<string | null>(null);
  const [hasMultiSession, setHasMultiSession] = useState(
    cachedMulti != null && cachedMulti.available && cachedMulti.sessions.length > 1
  );

  // Sub-view state — default to "changes" when diffs exist, else story
  const [subView, setSubView] = useState<ReviewSubView>(
    hasChanges ? "changes" : "story"
  );

  // Respond to externally-requested sub-view (e.g. "View step changes" from activity feed)
  useEffect(() => {
    if (requestedSubView) {
      setSubView(requestedSubView);
      onSubViewHandled?.();
    }
  }, [requestedSubView, onSubViewHandled]);

  useEffect(() => {
    // If we already have cached data, skip fetch
    if (cachedMulti != null) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchMultiSession(jobId).then((multi) => {
      if (cancelled) return;
      setMultiSession(jobId, multi);
      setHasMultiSession(multi.available && multi.sessions.length > 1);
    }).catch((err) => {
      if (!cancelled) setError(err?.message ?? "Failed to load review data");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, [jobId, cachedMulti, setMultiSession]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
        <AlertTriangle size={16} className="text-yellow-400" />
        <span>{error}</span>
      </div>
    );
  }

  const showTimeline = hasMultiSession;

  return (
    <div className="flex flex-col h-full">
      {/* Sub-view tabs */}
      <ReviewSubTabs
        active={subView}
        onChange={setSubView}
        showChanges={hasChanges}
        showTimeline={showTimeline}
      />

      {/* Sub-view content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {subView === "changes" && hasChanges && (
          <Suspense fallback={<div className="flex justify-center py-10"><Spinner /></div>}>
            <DiffViewer
              jobId={jobId}
              jobState={jobState}
              resolution={resolution}
              archivedAt={archivedAt}
              onAskSent={onAskSent}
              stepFilter={stepFilter}
              onClearStepFilter={onClearStepFilter}
              onNavigateToStep={onNavigateToStep}
            />
          </Suspense>
        )}
        {subView === "timeline" && showTimeline && (
          <TimelineSubView jobId={jobId} />
        )}
        {subView === "story" && (
          <StorySubView jobId={jobId} />
        )}
      </div>
    </div>
  );
}

export default ReviewDashboard;
