import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTowerStore, selectJobLogs } from "../store";

const LEVELS = ["debug", "info", "warn", "error"] as const;
type Level = (typeof LEVELS)[number];

const ESTIMATED_ROW_HEIGHT = 24;

export function LogsPanel({ jobId }: { jobId: string }) {
  const logs = useTowerStore(selectJobLogs(jobId));
  const [enabledLevels, setEnabledLevels] = useState<Set<Level>>(
    new Set(["info", "warn", "error"]),
  );
  const parentRef = useRef<HTMLDivElement>(null);
  const wasAtBottom = useRef(true);

  const filteredLogs = useMemo(
    () => logs.filter((l) => enabledLevels.has(l.level as Level)),
    [logs, enabledLevels],
  );

  const virtualizer = useVirtualizer({
    count: filteredLogs.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 20,
  });

  // Track whether user is at bottom before new items arrive
  const onScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    wasAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  // Auto-scroll to bottom when new logs arrive, only if user was at bottom
  useEffect(() => {
    if (wasAtBottom.current && filteredLogs.length > 0) {
      virtualizer.scrollToIndex(filteredLogs.length - 1, { align: "end" });
    }
  }, [filteredLogs.length, virtualizer]);

  function toggleLevel(level: Level) {
    setEnabledLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  }

  return (
    <div className="panel">
      <div className="panel__header">
        <span>Logs</span>
        <div className="log-filters">
          {LEVELS.map((level) => (
            <button
              key={level}
              className={`log-filter log-filter--${level} ${enabledLevels.has(level) ? "log-filter--active" : ""}`}
              onClick={() => toggleLevel(level)}
            >
              {level}
            </button>
          ))}
        </div>
      </div>
      <div
        ref={parentRef}
        className="panel__body"
        onScroll={onScroll}
        style={{ overflow: "auto" }}
      >
        {filteredLogs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__text">No log entries</div>
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
              const line = filteredLogs[virtualItem.index]!;
              return (
                <div
                  key={`${line.jobId}-${line.seq}`}
                  className="log-line"
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
                  <span className="log-line__time">
                    {new Date(line.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={`log-line__level log-line__level--${line.level}`}>
                    {line.level}
                  </span>
                  <span className="log-line__msg">{line.message}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
