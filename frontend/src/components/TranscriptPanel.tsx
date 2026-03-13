import { useRef, useEffect, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTowerStore, selectJobTranscript } from "../store";

const ESTIMATED_ROW_HEIGHT = 60;

export function TranscriptPanel({ jobId }: { jobId: string }) {
  const transcript = useTowerStore(selectJobTranscript(jobId));
  const parentRef = useRef<HTMLDivElement>(null);
  const wasAtBottom = useRef(true);

  const virtualizer = useVirtualizer({
    count: transcript.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 10,
  });

  const onScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    wasAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (wasAtBottom.current && transcript.length > 0) {
      virtualizer.scrollToIndex(transcript.length - 1, { align: "end" });
    }
  }, [transcript.length, virtualizer]);

  return (
    <div className="panel">
      <div className="panel__header">
        <span>Transcript</span>
        <span style={{ fontSize: 11 }}>{transcript.length} messages</span>
      </div>
      <div
        ref={parentRef}
        className="panel__body"
        onScroll={onScroll}
        style={{ overflow: "auto" }}
      >
        {transcript.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__text">No transcript entries yet</div>
          </div>
        ) : (
          <div
            style={{
              height: virtualizer.getTotalSize(),
              width: "100%",
              position: "relative",
            }}
          >
            {virtualizer.getVirtualItems().map((virtualItem) => {
              const entry = transcript[virtualItem.index]!;
              return (
                <div
                  key={`${entry.jobId}-${entry.seq}`}
                  className="transcript-entry"
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                >
                  <div
                    className={`transcript-entry__role transcript-entry__role--${entry.role}`}
                  >
                    {entry.role}
                  </div>
                  <div className="transcript-entry__content">{entry.content}</div>
                  <div className="transcript-entry__time">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
