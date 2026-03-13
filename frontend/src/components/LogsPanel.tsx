import { useState, useRef, useEffect } from "react";
import { useTowerStore, selectJobLogs } from "../store";
import { Card, CardHeader, CardTitle } from "../ui/Card";
import { EmptyState } from "../ui/Feedback";
import { cn } from "../ui/cn";

const LEVELS = ["debug", "info", "warn", "error"] as const;

const levelColor: Record<string, string> = {
  debug: "text-text-dim",
  info: "text-accent",
  warn: "text-warning",
  error: "text-error",
};

export function LogsPanel({ jobId }: { jobId: string }) {
  const allLogs = useTowerStore(selectJobLogs(jobId));
  const [filter, setFilter] = useState<Set<string>>(new Set(LEVELS));
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const logs = allLogs.filter((l) => filter.has(l.level));

  useEffect(() => {
    if (stickRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const toggleLevel = (level: string) => {
    setFilter((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  };

  return (
    <Card className="flex flex-col max-h-[500px]">
      <CardHeader>
        <CardTitle>Logs</CardTitle>
        <div className="flex gap-1">
          {LEVELS.map((level) => (
            <button
              key={level}
              onClick={() => toggleLevel(level)}
              className={cn(
                "px-2 py-0.5 rounded text-[11px] font-medium uppercase cursor-pointer transition-colors",
                filter.has(level)
                  ? cn("border border-border bg-surface-hover", levelColor[level])
                  : "text-text-dim border border-transparent"
              )}
            >
              {level}
            </button>
          ))}
        </div>
      </CardHeader>
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto min-h-0 font-mono text-xs">
        {logs.length === 0 ? (
          <EmptyState text="No log entries" />
        ) : (
          logs.map((log, i) => (
            <div key={i} className="flex gap-2 px-4 py-0.5 hover:bg-surface-hover leading-relaxed">
              <span className="text-text-dim whitespace-nowrap shrink-0">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
              <span className={cn("w-10 shrink-0 font-semibold uppercase", levelColor[log.level])}>
                {log.level}
              </span>
              <span className="whitespace-pre-wrap break-all">{log.message}</span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}
