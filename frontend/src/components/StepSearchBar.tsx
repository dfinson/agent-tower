import { Search, X, ChevronUp, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "../lib/utils";
import { fetchTranscriptSearch } from "../api/client";
import { useStore, selectJobSteps } from "../store";

interface SearchResult {
  seq: number;
  role: string;
  content: string;
  toolName: string | null;
  stepId: string | null;
  stepNumber: number | null;
  timestamp: string;
}

export type FilterChipKey = "errors" | "tools" | "agent" | "files" | "running";

interface FilterChipDisplay {
  key: FilterChipKey;
  label: string;
  count?: number;
}

interface StepSearchBarProps {
  jobId: string;
  onSelect?: (result: SearchResult) => void;
  activeFilter?: FilterChipKey | null;
  onFilterChange?: (filter: FilterChipKey | null) => void;
  /** Only chips with data to show — computed by parent from step state */
  visibleChips?: FilterChipDisplay[];
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Highlight all occurrences of `term` in `text` — case-insensitive. */
function HighlightedText({ text, term }: { text: string; term: string }) {
  if (!term || term.length < 2) return <>{text}</>;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === term.toLowerCase() ? (
          <mark key={i} className="bg-yellow-400/30 text-foreground rounded-sm px-0.5">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/** Group results by step for the persistent results panel. */
function groupByStep(results: SearchResult[]): { stepId: string | null; stepNumber: number | null; items: SearchResult[] }[] {
  const groups: { stepId: string | null; stepNumber: number | null; items: SearchResult[] }[] = [];
  const map = new Map<string, typeof groups[number]>();
  for (const r of results) {
    const key = r.stepId ?? "__no_step__";
    let group = map.get(key);
    if (!group) {
      group = { stepId: r.stepId, stepNumber: r.stepNumber, items: [] };
      map.set(key, group);
      groups.push(group);
    }
    group.items.push(r);
  }
  return groups;
}

/** Human-readable label for transcript roles. */
function roleLabel(r: SearchResult): string {
  switch (r.role) {
    case "agent": return "Agent";
    case "tool_call": return r.toolName ?? "Tool";
    case "tool_result": return r.toolName ? `${r.toolName} result` : "Tool result";
    case "tool_running": return r.toolName ?? "Tool running";
    case "operator": return "You";
    case "system": return "System";
    default: return r.role;
  }
}

function roleColor(role: string): string {
  switch (role) {
    case "agent": return "text-blue-500";
    case "tool_call":
    case "tool_running": return "text-amber-500";
    case "tool_result": return "text-emerald-500";
    case "operator": return "text-primary";
    default: return "";
  }
}

export function StepSearchBar({ jobId, onSelect, activeFilter, onFilterChange, visibleChips }: StepSearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [isSearching, setIsSearching] = useState(false);
  const debouncedQuery = useDebounce(query, 300);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultPanelRef = useRef<HTMLDivElement>(null);

  // Map stepId → label for group headers
  const planSteps = useStore(selectJobSteps(jobId));
  const stepLabelMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of planSteps) m.set(s.stepId, s.label);
    return m;
  }, [planSteps]);

  useEffect(() => {
    if (!debouncedQuery || debouncedQuery.length < 2) {
      setResults([]);
      setActiveIdx(-1);
      return;
    }
    setIsSearching(true);
    fetchTranscriptSearch(jobId, debouncedQuery, { limit: 100 })
      .then((r) => { setResults(r); setActiveIdx(r.length > 0 ? 0 : -1); })
      .catch(() => { setResults([]); setActiveIdx(-1); })
      .finally(() => setIsSearching(false));
  }, [jobId, debouncedQuery]);

  const navigateTo = useCallback((idx: number) => {
    if (idx < 0 || idx >= results.length) return;
    setActiveIdx(idx);
    const r = results[idx];
    if (r) onSelect?.(r);
  }, [results, onSelect]);

  const goNext = useCallback(() => {
    if (results.length === 0) return;
    const next = activeIdx < results.length - 1 ? activeIdx + 1 : 0;
    navigateTo(next);
  }, [activeIdx, results.length, navigateTo]);

  const goPrev = useCallback(() => {
    if (results.length === 0) return;
    const prev = activeIdx > 0 ? activeIdx - 1 : results.length - 1;
    navigateTo(prev);
  }, [activeIdx, results.length, navigateTo]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault();
      goNext();
    } else if (e.key === "ArrowUp" || (e.key === "Enter" && e.shiftKey)) {
      e.preventDefault();
      goPrev();
    } else if (e.key === "Escape") {
      setQuery("");
      setResults([]);
      setActiveIdx(-1);
      inputRef.current?.blur();
    }
  }, [goNext, goPrev]);

  const clearSearch = useCallback(() => {
    setQuery("");
    setResults([]);
    setActiveIdx(-1);
  }, []);

  const grouped = useMemo(() => groupByStep(results), [results]);
  const hasResults = results.length > 0;
  const showPanel = query.length >= 2;

  // Scroll active result into view in the panel
  useEffect(() => {
    if (activeIdx < 0 || !resultPanelRef.current) return;
    const el = resultPanelRef.current.querySelector(`[data-result-idx="${activeIdx}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  return (
    <div className="relative">
      {/* Search input row */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border/50">
        <Search size={14} className="text-muted-foreground shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search transcript…"
          aria-label="Search transcript"
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
        />
        {/* Result count + navigation */}
        {showPanel && (
          <div className="flex items-center gap-1 shrink-0">
            {isSearching ? (
              <span className="text-xs text-muted-foreground animate-pulse">…</span>
            ) : (
              <span className="text-xs text-muted-foreground tabular-nums">
                {hasResults ? `${activeIdx + 1}/${results.length}` : "0 results"}
              </span>
            )}
            <button
              onClick={goPrev}
              disabled={!hasResults}
              className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"
              aria-label="Previous result (Shift+Enter)"
            >
              <ChevronUp size={14} />
            </button>
            <button
              onClick={goNext}
              disabled={!hasResults}
              className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-30"
              aria-label="Next result (Enter)"
            >
              <ChevronDown size={14} />
            </button>
          </div>
        )}
        {query && (
          <button
            onClick={clearSearch}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Clear search"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Filter chips — only shown when relevant data exists */}
      {onFilterChange && visibleChips && visibleChips.length > 0 && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 overflow-x-auto border-b border-border/50">
          {visibleChips.map((chip) => (
            <button
              key={chip.key}
              onClick={() => onFilterChange(activeFilter === chip.key ? null : chip.key)}
              aria-pressed={activeFilter === chip.key}
              className={cn(
                "shrink-0 px-2 py-0.5 rounded-full text-xs transition-colors min-h-[28px]",
                activeFilter === chip.key
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              {chip.label}{chip.count != null ? ` (${chip.count})` : ""}
            </button>
          ))}
        </div>
      )}

      {/* Persistent results panel — grouped by step */}
      {showPanel && hasResults && (
        <div
          ref={resultPanelRef}
          role="listbox"
          aria-label="Search results"
          className="border-b border-border bg-muted/30 max-h-72 overflow-y-auto"
        >
          {grouped.map((group) => (
            <div key={group.stepId ?? "__none"}>
              {/* Step group header */}
              <div className="sticky top-0 z-[1] flex items-center gap-2 px-4 py-1 bg-muted/70 backdrop-blur-sm border-b border-border/30">
                <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider truncate">
                  {group.stepId ? (stepLabelMap.get(group.stepId) ?? `Step ${group.stepNumber ?? "?"}`) : "General"}
                </span>
                <span className="text-[10px] text-muted-foreground/60 shrink-0">
                  {group.items.length} match{group.items.length !== 1 ? "es" : ""}
                </span>
              </div>
              {/* Results within step */}
              {group.items.map((r) => {
                const globalIdx = results.indexOf(r);
                const isActive = globalIdx === activeIdx;
                return (
                  <button
                    key={r.seq}
                    role="option"
                    aria-selected={isActive}
                    data-result-idx={globalIdx}
                    onClick={() => navigateTo(globalIdx)}
                    className={cn(
                      "w-full text-left px-4 py-1.5 text-sm transition-colors border-b border-border/20 last:border-0",
                      isActive ? "bg-primary/10 border-l-2 border-l-primary" : "hover:bg-accent/50",
                    )}
                  >
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-0.5">
                      <span className={cn("font-medium", roleColor(r.role))}>
                        {roleLabel(r)}
                      </span>
                    </div>
                    <div className="text-xs text-foreground/80 line-clamp-2 leading-relaxed">
                      <HighlightedText text={r.content} term={debouncedQuery} />
                    </div>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {/* No results feedback */}
      {showPanel && !hasResults && !isSearching && (
        <div className="px-4 py-3 border-b border-border/50 text-center">
          <span className="text-xs text-muted-foreground">No matches for "{debouncedQuery}"</span>
        </div>
      )}
    </div>
  );
}
