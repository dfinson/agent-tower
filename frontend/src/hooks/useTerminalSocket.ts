/**
 * React hook that bridges an xterm.js Terminal instance with a WebSocket
 * connection to the CodePlane terminal backend.
 *
 * Handles: attach/detach, input/output streaming, resize, reconnection,
 * and scrollback replay.
 */

import { useEffect, useRef, useCallback } from "react";
import type { Terminal } from "@xterm/xterm";

function getWsBase(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

interface UseTerminalSocketOptions {
  /** The xterm.js Terminal instance to bridge. */
  terminal: Terminal | null;
  /** The terminal session ID to attach to. */
  sessionId: string | null;
  /** Called when the server reports the session has exited. */
  onExit?: (code: number) => void;
}

export function useTerminalSocket({ terminal, sessionId, onExit }: UseTerminalSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionIdRef = useRef(sessionId);
  const attemptRef = useRef(0);
  sessionIdRef.current = sessionId;

  const connect = useCallback(() => {
    if (!terminal || !sessionIdRef.current) return;

    const ws = new WebSocket(`${getWsBase()}/api/terminal/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      // Attach to session
      ws.send(JSON.stringify({ type: "attach", sessionId: sessionIdRef.current }));
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "output":
            terminal.write(msg.data);
            break;
          case "attached":
            // Send initial size
            ws.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }));
            break;
          case "exit":
            onExit?.(msg.code);
            break;
          case "error":
            console.warn("[terminal] Server error:", msg.message);
            break;
        }
      } catch {
        // Ignore unparseable messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      // Auto-reconnect with exponential backoff if session is still active
      if (sessionIdRef.current) {
        attemptRef.current += 1;
        const MAX_WS_ATTEMPTS = 20;
        if (attemptRef.current > MAX_WS_ATTEMPTS) {
          console.warn("[terminal] Max reconnect attempts reached");
          return;
        }
        const delay = Math.min(1000 * 2 ** (attemptRef.current - 1), 30_000);
        reconnectTimer.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [terminal, onExit]);

  // Connect when terminal and sessionId are ready
  useEffect(() => {
    if (!terminal || !sessionId) return;

    connect();

    // Bridge xterm input → WebSocket
    const inputDisposable = terminal.onData((data: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "input", data }));
      }
    });

    // Bridge terminal resize → WebSocket
    const resizeDisposable = terminal.onResize(({ cols, rows }: { cols: number; rows: number }) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });

    return () => {
      inputDisposable.dispose();
      resizeDisposable.dispose();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent auto-reconnect
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [terminal, sessionId, connect]);

  // Send a detach when sessionId changes
  useEffect(() => {
    return () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "detach" }));
      }
    };
  }, [sessionId]);
}
