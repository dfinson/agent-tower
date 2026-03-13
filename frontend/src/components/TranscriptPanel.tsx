import { useRef, useEffect } from "react";
import { useTowerStore, selectJobTranscript } from "../store";
import { Card, CardHeader, CardTitle } from "../ui/Card";
import { EmptyState } from "../ui/Feedback";
import { cn } from "../ui/cn";

export function TranscriptPanel({ jobId }: { jobId: string }) {
  const entries = useTowerStore(selectJobTranscript(jobId));
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    if (stickRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  return (
    <Card className="flex flex-col max-h-[500px]">
      <CardHeader>
        <CardTitle>Transcript</CardTitle>
        <span className="text-xs text-text-dim">{entries.length} messages</span>
      </CardHeader>
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto min-h-0">
        {entries.length === 0 ? (
          <EmptyState text="No transcript entries yet" />
        ) : (
          entries.map((e, i) => (
            <div key={i} className="px-4 py-2 border-b border-border last:border-b-0">
              <div className={cn(
                "text-[11px] font-semibold uppercase tracking-wide mb-1",
                e.role === "agent" ? "text-accent" : "text-success"
              )}>
                {e.role}
              </div>
              <div className="text-[13px] leading-relaxed whitespace-pre-wrap">{e.content}</div>
              <div className="text-[10px] text-text-dim mt-1">
                {new Date(e.timestamp).toLocaleTimeString()}
              </div>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
