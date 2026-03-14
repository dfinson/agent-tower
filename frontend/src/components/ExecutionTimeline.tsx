import { useMemo } from "react";
import { Paper, Group, Text, ScrollArea } from "@mantine/core";
import { useTowerStore, selectJobLogs } from "../store";

function isTimelineEvent(msg: string, level: string): boolean {
  if (level === "error") return true;
  const lower = msg.toLowerCase();
  return ["state", "started", "completed", "created", "failed", "succeeded", "canceled", "approval"].some(
    (kw) => lower.includes(kw)
  );
}

function dotColor(level: string, msg: string): string {
  if (level === "error") return "bg-red-500";
  const lower = msg.toLowerCase();
  if (lower.includes("succeeded") || lower.includes("completed")) return "bg-green-500";
  if (lower.includes("running") || lower.includes("started")) return "bg-blue-500";
  if (lower.includes("failed") || lower.includes("canceled")) return "bg-red-500";
  return "bg-[var(--mantine-color-dark-3)]";
}

export function ExecutionTimeline({ jobId }: { jobId: string }) {
  const logs = useTowerStore(selectJobLogs(jobId));
  const events = useMemo(
    () => logs.filter((l) => isTimelineEvent(l.message, l.level)),
    [logs]
  );

  return (
    <Paper className="flex flex-col overflow-hidden" radius="lg" p={0}>
      <Group className="px-4 py-2.5 border-b border-[var(--mantine-color-dark-4)]">
        <Text size="sm" fw={600} c="dimmed">Timeline</Text>
      </Group>
      <ScrollArea className="max-h-[300px]">
        {events.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">No timeline events yet</Text>
        ) : (
          <div className="p-4 space-y-1">
            {events.map((e, i) => (
              <div key={i} className="flex items-start gap-3 py-1 text-xs">
                <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${dotColor(e.level, e.message)}`} />
                <span className="text-[var(--mantine-color-dimmed)] font-mono shrink-0">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-[var(--mantine-color-dark-1)]">{e.message}</span>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </Paper>
  );
}
