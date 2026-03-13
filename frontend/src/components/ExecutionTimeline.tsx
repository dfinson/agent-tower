import { useMemo } from "react";
import { useTowerStore, selectJobLogs } from "../store";
import { Card, CardHeader, CardTitle } from "../ui/Card";
import { EmptyState } from "../ui/Feedback";
import { cn } from "../ui/cn";

function isTimelineEvent(msg: string, level: string): boolean {
  if (level === "error") return true;
  const lower = msg.toLowerCase();
  return ["state", "started", "completed", "created", "failed", "succeeded", "canceled", "approval"].some(
    (kw) => lower.includes(kw)
  );
}

function dotVariant(level: string, msg: string): string {
  if (level === "error") return "bg-error";
  const lower = msg.toLowerCase();
  if (lower.includes("succeeded") || lower.includes("completed")) return "bg-success";
  if (lower.includes("running") || lower.includes("started")) return "bg-accent";
  if (lower.includes("failed") || lower.includes("canceled")) return "bg-error";
  return "bg-border";
}

export function ExecutionTimeline({ jobId }: { jobId: string }) {
  const logs = useTowerStore(selectJobLogs(jobId));
  const events = useMemo(
    () => logs.filter((l) => isTimelineEvent(l.message, l.level)),
    [logs]
  );

  return (
    <Card className="flex flex-col max-h-[500px]">
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
      </CardHeader>
      <div className="flex-1 overflow-y-auto min-h-0 p-4">
        {events.length === 0 ? (
          <EmptyState text="No timeline events yet" />
        ) : (
          events.map((e, i) => (
            <div key={i} className="flex items-start gap-2 py-1 text-xs">
              <div className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0", dotVariant(e.level, e.message))} />
              <span className="text-text-dim font-mono shrink-0">
                {new Date(e.timestamp).toLocaleTimeString()}
              </span>
              <span className="text-text-muted">{e.message}</span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
