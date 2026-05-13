import { useState, useEffect } from "react";
import { Clock, Zap } from "lucide-react";
import { useStore } from "../store";
import { interruptJob } from "../api/client";

function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/**
 * Shows how long the agent has been idle and what tool is active.
 * Provides an interrupt button. No automatic timeouts — the user decides.
 */
export function IdleIndicator({ jobId }: { jobId: string }) {
  const heartbeat = useStore((s) => s.jobHeartbeats[jobId]);
  const job = useStore((s) => s.jobs[jobId]);
  const [now, setNow] = useState(Date.now());
  const [interrupting, setInterrupting] = useState(false);

  // Tick every second to update elapsed time
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!heartbeat?.lastActivityAt || job?.state !== "running") return null;

  const lastActivity = new Date(heartbeat.lastActivityAt).getTime();
  const elapsed = now - lastActivity;

  // Don't show anything if activity is recent (< 60s)
  if (elapsed < 60_000) return null;

  const handleInterrupt = async () => {
    setInterrupting(true);
    try {
      await interruptJob(jobId);
    } finally {
      setInterrupting(false);
    }
  };

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="flex items-center gap-1 text-yellow-400/80">
        <Clock size={12} />
        <span>
          Idle {formatDuration(elapsed)}
          {heartbeat.activeToolName && (
            <> — waiting on <code className="px-1 py-0.5 rounded bg-muted text-[10px]">{heartbeat.activeToolName}</code></>
          )}
        </span>
      </span>
      <button
        onClick={handleInterrupt}
        disabled={interrupting}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium
                   bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20 border border-yellow-500/20
                   disabled:opacity-50 transition-colors"
      >
        <Zap size={10} />
        {interrupting ? "Interrupting…" : "Interrupt"}
      </button>
    </div>
  );
}
