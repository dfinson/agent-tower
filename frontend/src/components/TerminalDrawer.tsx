/**
 * TerminalDrawer — persistent bottom drawer that houses terminal sessions.
 *
 * Rendered at the App level (outside <Routes>) so it persists across
 * page navigation. Supports multiple session tabs, resize via drag, and
 * collapse/expand.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, X, Minus, Maximize2, GitBranch, Search } from "lucide-react";
import { TerminalPanel } from "./TerminalPanel";
import { useStore } from "../store";
import { useShallow } from "zustand/react/shallow";
import { Tooltip } from "./ui/tooltip";
import { useDrag } from "../hooks/useDrag";
import type { TerminalConnectionStatus } from "../hooks/useTerminalSocket";
import type { SearchAddon } from "@xterm/addon-search";
import { cn } from "../lib/utils";

const MIN_HEIGHT = 150;
const DEFAULT_HEIGHT = 300;
const MAX_HEIGHT_RATIO = 0.7;

export function TerminalDrawer() {
  const {
    terminalDrawerOpen,
    terminalSessions,
    activeTerminalTab,
    terminalDrawerHeight,
    toggleTerminalDrawer,
    setActiveTerminalTab,
    removeTerminalSession,
    setTerminalDrawerHeight,
    createTerminalSession,
  } = useStore(useShallow((s) => ({
    terminalDrawerOpen: s.terminalDrawerOpen,
    terminalSessions: s.terminalSessions,
    activeTerminalTab: s.activeTerminalTab,
    terminalDrawerHeight: s.terminalDrawerHeight,
    toggleTerminalDrawer: s.toggleTerminalDrawer,
    setActiveTerminalTab: s.setActiveTerminalTab,
    removeTerminalSession: s.removeTerminalSession,
    setTerminalDrawerHeight: s.setTerminalDrawerHeight,
    createTerminalSession: s.createTerminalSession,
  })));

  const [maximized, setMaximized] = useState(false);
  const [connectionStatuses, setConnectionStatuses] = useState<Record<string, TerminalConnectionStatus>>({});
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const searchAddonRef = useRef<SearchAddon | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const sessionList = Object.values(terminalSessions);

  // Auto-create a session when the drawer opens with no sessions at all
  useEffect(() => {
    if (terminalDrawerOpen && sessionList.length === 0) {
      createTerminalSession();
    }
  }, [terminalDrawerOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle drag-to-resize
  const dragHandlers = useDrag({
    axis: "y",
    onDrag: (delta) => {
      const maxH = window.innerWidth < 640
        ? window.innerHeight * 0.5
        : window.innerHeight * MAX_HEIGHT_RATIO;
      setTerminalDrawerHeight(Math.min(Math.max(terminalDrawerHeight + delta, MIN_HEIGHT), maxH));
    },
  });

  const handleNewSession = useCallback(() => {
    createTerminalSession();
  }, [createTerminalSession]);

  const handleCloseSession = useCallback(
    (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      removeTerminalSession(id);
    },
    [removeTerminalSession],
  );

  const toggleMaximize = useCallback(() => {
    if (maximized) {
      setTerminalDrawerHeight(DEFAULT_HEIGHT);
    } else {
      setTerminalDrawerHeight(window.innerHeight * MAX_HEIGHT_RATIO);
    }
    setMaximized(!maximized);
  }, [maximized, setTerminalDrawerHeight]);

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
    if (searchAddonRef.current) {
      if (query) searchAddonRef.current.findNext(query);
      else searchAddonRef.current.clearDecorations();
    }
  }, []);

  const handleSearchNext = useCallback(() => {
    if (searchAddonRef.current && searchQuery) searchAddonRef.current.findNext(searchQuery);
  }, [searchQuery]);

  const handleSearchPrev = useCallback(() => {
    if (searchAddonRef.current && searchQuery) searchAddonRef.current.findPrevious(searchQuery);
  }, [searchQuery]);

  const toggleSearch = useCallback(() => {
    setSearchOpen((prev) => {
      if (!prev) setTimeout(() => searchInputRef.current?.focus(), 50);
      else {
        searchAddonRef.current?.clearDecorations();
        setSearchQuery("");
      }
      return !prev;
    });
  }, []);

  // Keyboard shortcut: Ctrl+Shift+F to toggle search
  useEffect(() => {
    if (!terminalDrawerOpen) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "f") {
        e.preventDefault();
        toggleSearch();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [terminalDrawerOpen, toggleSearch]);

  const handleStatusChange = useCallback((sessionId: string, status: TerminalConnectionStatus) => {
    setConnectionStatuses((prev) => ({ ...prev, [sessionId]: status }));
  }, []);

  if (!terminalDrawerOpen) return null;

  const height = terminalDrawerHeight || DEFAULT_HEIGHT;
  const activeStatus = activeTerminalTab ? connectionStatuses[activeTerminalTab] : undefined;

  return (
    <div
      className="border-t border-border bg-card flex flex-col shrink-0"
      style={{ height, paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      {/* Drag handle */}
      <div
        className="h-7 cursor-row-resize hover:bg-primary/20 active:bg-primary/30 transition-colors shrink-0 flex items-center justify-center touch-none group"
        {...dragHandlers}
      >
        <div className="w-10 h-1 bg-muted-foreground/40 group-hover:bg-primary/50 group-active:bg-primary/70 rounded-full transition-colors" />
      </div>

      {/* Tab bar */}
      <div
        className="flex items-center h-8 shrink-0 border-b border-border px-1 gap-0.5 overflow-x-auto"
        role="tablist"
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault();
            const idx = sessionList.findIndex((s) => s.id === activeTerminalTab);
            const next = e.key === "ArrowRight"
              ? sessionList[(idx + 1) % sessionList.length]
              : sessionList[(idx - 1 + sessionList.length) % sessionList.length];
            if (next) setActiveTerminalTab(next.id);
          }
        }}
      >
        {sessionList.map((session) => {
          const status = connectionStatuses[session.id];
          return (
          <button
            key={session.id}
            role="tab"
            aria-selected={activeTerminalTab === session.id}
            onClick={() => setActiveTerminalTab(session.id)}
            className={`flex items-center gap-1.5 px-2.5 h-7 rounded-sm text-xs font-medium transition-colors shrink-0 ${
              activeTerminalTab === session.id
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
            }`}
          >
            <span className={cn(
              "w-1.5 h-1.5 rounded-full shrink-0",
              status === "connected" ? "bg-green-500" :
              status === "connecting" || status === "reconnecting" ? "bg-yellow-500 animate-pulse" :
              status === "disconnected" ? "bg-red-500" :
              "bg-muted-foreground/40"
            )} />
            {session.jobId && (
              <GitBranch size={9} className="text-muted-foreground/60 shrink-0 -mr-0.5" />
            )}
            <span className="max-w-[120px] sm:max-w-[180px] truncate">
              {session.label || session.cwd?.split("/").pop() || "Terminal"}
            </span>
            <button
              type="button"
              onClick={(e) => handleCloseSession(session.id, e)}
              aria-label="Close terminal tab"
              className="ml-0.5 p-1 sm:p-0.5 min-h-[44px] sm:min-h-7 min-w-[44px] sm:min-w-7 rounded hover:bg-muted-foreground/20 flex items-center justify-center"
            >
              <X size={12} aria-hidden="true" />
            </button>
          </button>
          );
        })}

        <Tooltip content="New terminal session">
          <button
            onClick={handleNewSession}
            className="flex items-center justify-center w-9 h-9 rounded-sm text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors shrink-0"
          >
            <Plus size={13} />
          </button>
        </Tooltip>

        <div className="flex-1" />

        {/* Connection status label for active tab */}
        {activeStatus && activeStatus !== "connected" && (
          <span className="text-[10px] text-muted-foreground/70 shrink-0 mr-1">
            {activeStatus === "connecting" ? "Connecting…" :
             activeStatus === "reconnecting" ? "Reconnecting…" :
             "Disconnected"}
          </span>
        )}

        <Tooltip content="Search terminal (Ctrl+Shift+F)">
          <button
            onClick={toggleSearch}
            className={cn(
              "p-2 rounded-sm transition-colors",
              searchOpen ? "text-primary bg-primary/10" : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
            )}
          >
            <Search size={12} />
          </button>
        </Tooltip>
        <Tooltip content={maximized ? "Restore" : "Maximize"}>
          <button
            onClick={toggleMaximize}
            className="p-2 rounded-sm text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          >
            <Maximize2 size={12} />
          </button>
        </Tooltip>
        <Tooltip content="Minimize terminal">
          <button
            onClick={toggleTerminalDrawer}
            className="p-2 rounded-sm text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          >
            <Minus size={12} />
          </button>
        </Tooltip>
      </div>

      {/* Search bar */}
      {searchOpen && (
        <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border bg-card shrink-0">
          <Search size={12} className="text-muted-foreground shrink-0" />
          <input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(e) => handleSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                e.shiftKey ? handleSearchPrev() : handleSearchNext();
              }
              if (e.key === "Escape") {
                e.preventDefault();
                toggleSearch();
              }
            }}
            placeholder="Find in terminal…"
            className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground/50 outline-none min-w-0"
          />
          <button onClick={handleSearchPrev} className="p-1 rounded text-muted-foreground hover:text-foreground" aria-label="Previous match">&#x25B2;</button>
          <button onClick={handleSearchNext} className="p-1 rounded text-muted-foreground hover:text-foreground" aria-label="Next match">&#x25BC;</button>
          <button onClick={toggleSearch} className="p-1 rounded text-muted-foreground hover:text-foreground" aria-label="Close search">
            <X size={12} />
          </button>
        </div>
      )}

      {/* Terminal area */}
      <div className="flex-1 min-h-0">
        {activeTerminalTab && terminalSessions[activeTerminalTab] ? (
          <TerminalPanel
            sessionId={activeTerminalTab}
            searchAddonRef={searchAddonRef}
            onStatusChange={(status) => handleStatusChange(activeTerminalTab, status)}
            onExit={() => {
              // Terminal process exited — no action needed
            }}
          />
        ) : sessionList.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            <button onClick={handleNewSession} className="flex items-center gap-2 hover:text-foreground transition-colors">
              <Plus size={14} />
              Create a terminal session
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
