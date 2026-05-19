import { useState, useEffect } from "react";
import { Zap } from "lucide-react";
import { useStore } from "../store";
import { interruptJob } from "../api/client";
import { cn } from "../lib/utils";

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

type Severity = "silent" | "normal" | "warning" | "danger";

function getSeverity(elapsed: number): Severity {
  if (elapsed < 15_000) return "silent";
  if (elapsed < 60_000) return "normal";
  if (elapsed < 180_000) return "warning";
  return "danger";
}

const SEVERITY_STYLES: Record<Severity, { bar: string; text: string; border: string; button: string }> = {
  silent: { bar: "", text: "text-muted-foreground/60", border: "", button: "" },
  normal: { bar: "bg-blue-500/20", text: "text-blue-400/80", border: "border-blue-500/20", button: "bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border-blue-500/20" },
  warning: { bar: "bg-yellow-500/15", text: "text-yellow-400/80", border: "border-yellow-500/20", button: "bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 border-yellow-500/20" },
  danger: { bar: "bg-orange-500/15", text: "text-orange-400/80", border: "border-orange-500/20", button: "bg-orange-500/10 text-orange-400 hover:bg-orange-500/20 border-orange-500/20" },
};

/**
 * Inline progressive elapsed-time indicator for running tool calls.
 * Renders below the command/tool content with escalating severity.
 *
 * - 0–15s: nothing shown (fast tools don't need noise)
 * - 15–60s: subtle blue elapsed timer with animated pulse
 * - 60–180s: yellow "Running longer than usual" + [Interrupt] button
 * - 180s+: orange/red "Possibly stuck" + prominent [Interrupt]
 */
export function RunningToolIndicator({
  jobId,
  startedAt,
}: {
  jobId: string;
  startedAt: string;
}) {
  const job = useStore((s) => s.jobs[jobId]);
  const [now, setNow] = useState(Date.now());
  const [interrupting, setInterrupting] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (job?.state !== "running") return null;

  const startMs = new Date(startedAt).getTime();
  const elapsed = now - startMs;
  const severity = getSeverity(elapsed);

  // Don't render anything for fast tools
  if (severity === "silent") return null;

  const styles = SEVERITY_STYLES[severity];

  const handleInterrupt = async () => {
    setInterrupting(true);
    try {
      await interruptJob(jobId);
    } finally {
      setInterrupting(false);
    }
  };

  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-1.5 text-[11px]",
      styles.bar,
      styles.border && `border-t ${styles.border}`,
    )}>
      {/* Animated pulse dot */}
      <span className={cn(
        "w-1.5 h-1.5 rounded-full shrink-0",
        severity === "normal" && "bg-blue-400 animate-pulse",
        severity === "warning" && "bg-yellow-400 animate-pulse",
        severity === "danger" && "bg-orange-400 animate-[pulse_0.8s_ease-in-out_infinite]",
      )} />

      {/* Status text */}
      <span className={cn("flex-1", styles.text)}>
        {severity === "normal" && (
          <>running {formatElapsed(elapsed)}</>
        )}
        {severity === "warning" && (
          <>Running longer than usual — {formatElapsed(elapsed)}</>
        )}
        {severity === "danger" && (
          <>Possibly stuck — {formatElapsed(elapsed)}</>
        )}
      </span>

      {/* Interrupt button — appears at warning tier */}
      {(severity === "warning" || severity === "danger") && (
        <button
          onClick={handleInterrupt}
          disabled={interrupting}
          className={cn(
            "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium",
            "border transition-colors disabled:opacity-50",
            styles.button,
          )}
        >
          <Zap size={9} />
          {interrupting ? "Interrupting…" : "Interrupt"}
        </button>
      )}
    </div>
  );
}
