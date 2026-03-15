import { useState, useRef, useEffect } from "react";
import { useTowerStore, selectJobLogs } from "../store";
import { cn } from "../lib/utils";

const LEVELS = ["debug", "info", "warn", "error"] as const;

const LEVEL_CLASSES: Record<string, string> = {
  debug: "text-muted-foreground",
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
};

const LEVEL_DOT: Record<string, string> = {
  debug: "bg-muted-foreground",
  info: "bg-blue-400",
  warn: "bg-yellow-400",
  error: "bg-red-400",
};

export function LogsPanel({ jobId }: { jobId: string }) {
  const allLogs = useTowerStore(selectJobLogs(jobId));
  const [filter, setFilter] = useState<Set<string>>(new Set(LEVELS));
  const viewportRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const logs = allLogs.filter((l) => filter.has(l.level));

  useEffect(() => {
    if (stickRef.current && viewportRef.current) {
      viewportRef.current.scrollTo({ top: viewportRef.current.scrollHeight });
    }
  }, [logs.length]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
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
    <div className="flex flex-col h-full overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
        <span className="text-sm font-semibold text-muted-foreground">Logs</span>
        <div className="flex items-center gap-1">
          {LEVELS.map((level) => (
            <button
              key={level}
              type="button"
              onClick={() => toggleLevel(level)}
              className={cn(
                "flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border transition-colors",
                filter.has(level)
                  ? "border-transparent bg-muted text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              <span className={cn("w-1.5 h-1.5 rounded-full", LEVEL_DOT[level])} />
              {level}
            </button>
          ))}
        </div>
      </div>

      <div
        ref={viewportRef}
        className="flex-1 min-h-0 overflow-y-auto font-mono"
        onScroll={handleScroll}
      >
        {logs.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No logs</p>
        ) : (
          <div className="p-2 space-y-px">
            {logs.map((l, i) => (
              <div key={i} className="flex items-start gap-2 text-xs py-0.5 hover:bg-accent/30 px-1 rounded">
                <span className="text-muted-foreground shrink-0 tabular-nums">
                  {new Date(l.timestamp).toLocaleTimeString()}
                </span>
                <span className={cn("uppercase font-semibold w-10 shrink-0", LEVEL_CLASSES[l.level])}>
                  {l.level}
                </span>
                <span className="text-foreground/80 break-words min-w-0">{l.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
