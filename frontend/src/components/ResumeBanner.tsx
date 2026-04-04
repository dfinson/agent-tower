import { ArrowDown } from "lucide-react";
import { useStore, selectJobTranscript } from "../store";
import { useViewStateStore } from "../store/viewStateStore";

interface ResumeBannerProps {
  jobId: string;
  onJumpToFirst: () => void;
}

export function ResumeBanner({ jobId, onJumpToFirst }: ResumeBannerProps) {
  const lastSeen = useViewStateStore((s) => s.lastSeenSeq[jobId]);
  const transcript = useStore(selectJobTranscript(jobId));

  if (!lastSeen) return null;

  const newEntries = transcript.filter((e) => (e.seq ?? 0) > lastSeen);
  if (newEntries.length === 0) return null;

  const newStepIds = new Set(newEntries.map((e) => e.stepId).filter(Boolean));
  const newStepCount = newStepIds.size;
  const hasErrors = newEntries.some((e) => e.toolSuccess === false);

  return (
    <div className="flex items-center justify-between px-4 py-2 mb-3 rounded-lg bg-accent/50 border border-border text-sm">
      <div className="flex items-center gap-2">
        <ArrowDown size={14} />
        <span>
          {newStepCount > 0
            ? `${newStepCount} new step${newStepCount > 1 ? "s" : ""}`
            : `${newEntries.length} new events`}
          {hasErrors && (
            <span className="text-destructive ml-1">· errors detected</span>
          )}
        </span>
      </div>
      <button
        onClick={onJumpToFirst}
        className="text-xs font-medium text-primary hover:underline"
      >
        Jump to changes
      </button>
    </div>
  );
}
