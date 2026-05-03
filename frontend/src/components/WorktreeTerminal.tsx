/**
 * WorktreeTerminal — inline terminal for a job's worktree.
 *
 * Creates a real PTY session in the job's worktree directory and renders
 * it inline in the Shell tab. The session is created on first render and
 * persists across tab switches (the component is unmounted/remounted by
 * the tab system, so the session ID is lifted to the parent via a ref-like
 * callback).
 *
 * This is distinct from AgentTerminal, which is a read-only observer of
 * the agent's live execution and belongs in the TerminalDrawer.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { TerminalPanel } from "./TerminalPanel";
import { createTerminalSession, deleteTerminalSession } from "../api/client";
import type { TerminalConnectionStatus } from "../hooks/useTerminalSocket";
import { TerminalSquare, FolderX } from "lucide-react";
import { cn } from "../lib/utils";

interface WorktreeTerminalProps {
  jobId: string;
  worktreePath: string | null | undefined;
  className?: string;
}

export function WorktreeTerminal({ jobId, worktreePath, className }: WorktreeTerminalProps) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<TerminalConnectionStatus>("connecting");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  // Create a PTY session in the worktree on first mount.
  useEffect(() => {
    if (!worktreePath) return;
    if (sessionIdRef.current) {
      // Already have a session from a previous mount — reuse it.
      setSessionId(sessionIdRef.current);
      return;
    }

    let cancelled = false;
    setCreating(true);
    setError(null);

    createTerminalSession({ cwd: worktreePath, jobId })
      .then((data) => {
        if (cancelled) {
          // Component unmounted before session was created — clean up.
          deleteTerminalSession(data.id).catch(() => {});
          return;
        }
        sessionIdRef.current = data.id;
        setSessionId(data.id);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setCreating(false);
      });

    return () => {
      cancelled = true;
    };
  }, [jobId, worktreePath]);

  // Clean up the PTY session when the component is fully unmounted
  // (navigating away from the job, not just switching tabs).
  useEffect(() => {
    return () => {
      const id = sessionIdRef.current;
      if (id) {
        deleteTerminalSession(id).catch(() => {});
        sessionIdRef.current = null;
      }
    };
  }, [jobId]);

  const handleStatusChange = useCallback((s: TerminalConnectionStatus) => {
    setStatus(s);
  }, []);

  const handleExit = useCallback(() => {
    sessionIdRef.current = null;
    setSessionId(null);
  }, []);

  // No worktree — show empty state.
  if (!worktreePath) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground", className)}>
        <FolderX size={28} className="opacity-40" />
        <p className="text-sm">No worktree available.</p>
        <p className="text-xs opacity-60">
          A terminal will be available once the job has a worktree.
        </p>
      </div>
    );
  }

  // Creating session.
  if (creating) {
    return (
      <div className={cn("flex items-center justify-center gap-2 py-16 text-muted-foreground", className)}>
        <TerminalSquare size={16} className="animate-pulse" />
        <span className="text-sm">Opening terminal…</span>
      </div>
    );
  }

  // Error state.
  if (error) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground", className)}>
        <TerminalSquare size={28} className="opacity-40" />
        <p className="text-sm">Failed to open terminal.</p>
        <p className="text-xs opacity-60">{error}</p>
      </div>
    );
  }

  // No session yet (shouldn't happen if worktreePath is set, but guard).
  if (!sessionId) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground", className)}>
        <TerminalSquare size={28} className="opacity-40" />
        <p className="text-sm">No terminal session.</p>
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

      <TerminalPanel
        sessionId={sessionId}
        onExit={handleExit}
        onStatusChange={handleStatusChange}
        className="h-full"
      />
    </div>
  );
}
