/**
 * Runtime logs panel — custom console-like output viewer.
 *
 * Monospace, dark console background, auto-scrolling, level filtering.
 * Mantine used for shell. Content rendering is product-specific.
 */
import { useState, useRef, useEffect } from "react";
import { Paper, Group, Text, ScrollArea, Badge, UnstyledButton } from "@mantine/core";
import { useTowerStore, selectJobLogs } from "../store";

const LEVELS = ["debug", "info", "warn", "error"] as const;
const LEVEL_COLORS: Record<string, string> = {
  debug: "gray",
  info: "blue",
  warn: "yellow",
  error: "red",
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

  const handleScroll = (pos: { x: number; y: number }) => {
    const el = viewportRef.current;
    if (el) stickRef.current = el.scrollHeight - pos.y - el.clientHeight < 40;
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
    <Paper className="flex flex-col h-full overflow-hidden" radius="lg" p={0}>
      <Group
        justify="space-between"
        className="px-4 py-2.5 border-b border-[var(--mantine-color-dark-4)] shrink-0"
      >
        <Text size="sm" fw={600} c="dimmed">Logs</Text>
        <Group gap={4}>
          {LEVELS.map((level) => (
            <UnstyledButton key={level} onClick={() => toggleLevel(level)}>
              <Badge
                variant={filter.has(level) ? "light" : "outline"}
                color={LEVEL_COLORS[level]}
                size="xs"
                className="cursor-pointer"
              >
                {level}
              </Badge>
            </UnstyledButton>
          ))}
        </Group>
      </Group>

      <ScrollArea
        className="flex-1 min-h-0 bg-[#0d1117]"
        viewportRef={viewportRef}
        onScrollPositionChange={handleScroll}
      >
        {logs.length === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">No log entries</Text>
        ) : (
          <div className="p-2 font-mono text-xs leading-relaxed">
            {logs.map((log, i) => (
              <div key={i} className="flex gap-2 px-2 py-px hover:bg-white/5 rounded">
                <span className="text-[var(--mantine-color-dimmed)] whitespace-nowrap shrink-0">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
                <span className={`w-10 shrink-0 font-semibold uppercase text-[var(--mantine-color-${LEVEL_COLORS[log.level]}-5)]`}>
                  {log.level}
                </span>
                <span className="whitespace-pre-wrap break-all">{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </Paper>
  );
}
