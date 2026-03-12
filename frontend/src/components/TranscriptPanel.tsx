import { useRef, useEffect, useMemo } from "react";
import { useTowerStore, selectJobTranscript } from "../store";

export function TranscriptPanel({ jobId }: { jobId: string }) {
  const transcript = useTowerStore(selectJobTranscript(jobId));
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript.length]);

  const entries = useMemo(() => transcript, [transcript]);

  return (
    <div className="panel">
      <div className="panel__header">
        <span>Transcript</span>
        <span style={{ fontSize: 11 }}>{entries.length} messages</span>
      </div>
      <div className="panel__body">
        {entries.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__text">No transcript entries yet</div>
          </div>
        ) : (
          entries.map((entry, i) => (
            <div key={`${entry.jobId}-${entry.seq}-${i}`} className="transcript-entry">
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
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
