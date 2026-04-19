/**
 * AgentTerminal — observer terminal for live agent shell output.
 *
 * Connects to the backend observer terminal session for a running job,
 * displaying every shell command the agent executes in real time.
 *
 * On mobile, a floating Ctrl+C button is rendered so the operator can
 * interrupt a long-running command without needing a physical keyboard.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { TerminalPanel } from "./TerminalPanel";
import { fetchObserverTerminal, interruptJob } from "../api/client";
import type { TerminalConnectionStatus } from "../hooks/useTerminalSocket";
import { TerminalSquare, OctagonX } from "lucide-react";
import { cn } from "../lib/utils";

interface AgentTerminalProps {
  jobId: string;
  /** Whether the job is currently running. */
  isRunning: boolean;
  className?: string;
}

export function AgentTerminal({ jobId, isRunning, className }: AgentTerminalProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<TerminalConnectionStatus>("connecting");
  const [loading, setLoading] = useState(true);
  const [interruptPending, setInterruptPending] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout>>();

  // Discover the observer terminal session for this job.
  // Poll until found (the backend creates it when the job starts executing).
  useEffect(() => {
    let cancelled = false;

    async function discover() {
      setLoading(true);
      const info = await fetchObserverTerminal(jobId);
      if (cancelled) return;

      if (info) {
        setSessionId(info.id);
        setLoading(false);
      } else if (isRunning) {
        // Terminal not ready yet — retry shortly.
        pollRef.current = setTimeout(discover, 1500);
      } else {
        setLoading(false);
      }
    }

    discover();
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [jobId, isRunning]);

  const handleStatusChange = useCallback((s: TerminalConnectionStatus) => {
    setStatus(s);
  }, []);

  const handleCtrlC = useCallback(async () => {
    if (interruptPending) return;
    setInterruptPending(true);
    try {
      await interruptJob(jobId);
    } catch {
      // Interrupt is best-effort.
    } finally {
      // Brief cooldown so the user sees the press registered.
      setTimeout(() => setInterruptPending(false), 1200);
    }
  }, [jobId, interruptPending]);

  // Empty state: no observer terminal found and job is not running.
  if (!loading && !sessionId) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground", className)}>
        <TerminalSquare size={28} className="opacity-40" />
        <p className="text-sm">No agent terminal session available.</p>
        <p className="text-xs opacity-60">
          {isRunning
            ? "Waiting for the agent to start executing…"
            : "The agent terminal is available while the job is running."}
        </p>
      </div>
    );
  }

  // Loading state.
  if (loading) {
    return (
      <div className={cn("flex items-center justify-center gap-2 py-16 text-muted-foreground", className)}>
        <TerminalSquare size={16} className="animate-pulse" />
        <span className="text-sm">Connecting to agent terminal…</span>
      </div>
    );
  }

  return (
    <div className={cn("relative h-full", className)}>
      {/* Connection status pill */}
      {status !== "connected" && sessionId && (
        <div className="absolute top-2 right-2 z-10 flex items-center gap-1.5 rounded-full bg-background/80 backdrop-blur-sm border border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          <span
            className={cn(
              "inline-block w-1.5 h-1.5 rounded-full",
              status === "connecting" || status === "reconnecting"
                ? "bg-yellow-500 animate-pulse"
                : "bg-red-500",
            )}
          />
          {status === "connecting" && "Connecting…"}
          {status === "reconnecting" && "Reconnecting…"}
          {status === "disconnected" && "Disconnected"}
        </div>
      )}

      {/* Terminal */}
      <TerminalPanel
        sessionId={sessionId}
        onStatusChange={handleStatusChange}
        className="h-full"
      />

      {/* Mobile-only Ctrl+C button — floating in bottom-right.
          Touch-optimised: 48×48dp minimum, prominent but not blocking the
          terminal viewport.  Fades when the job is not running. */}
      {isRunning && (
        <button
          onClick={handleCtrlC}
          disabled={interruptPending}
          aria-label="Interrupt agent (Ctrl+C)"
          className={cn(
            "sm:hidden",
            "fixed bottom-20 right-4 z-50",
            "flex items-center justify-center",
            "w-14 h-14 rounded-full",
            "bg-red-600 text-white shadow-lg shadow-red-900/30",
            "active:scale-90 transition-all duration-150",
            interruptPending && "opacity-50 scale-95",
            !interruptPending && "hover:bg-red-500",
          )}
        >
          <OctagonX size={24} />
        </button>
      )}
    </div>
  );
}
