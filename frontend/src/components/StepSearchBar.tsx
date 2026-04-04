import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchTranscriptSearch } from "../api/client";

interface SearchResult {
  seq: number;
  role: string;
  content: string;
  toolName: string | null;
  stepId: string | null;
  stepNumber: number | null;
  timestamp: string;
}

interface StepSearchBarProps {
  jobId: string;
  onSelect?: (result: SearchResult) => void;
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function StepSearchBar({ jobId, onSelect }: StepSearchBarProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const debouncedQuery = useDebounce(query, 300);

  useEffect(() => {
    if (!debouncedQuery || debouncedQuery.length < 2) {
      setResults([]);
      return;
    }
    fetchTranscriptSearch(jobId, debouncedQuery)
      .then(setResults)
      .catch(() => setResults([]));
  }, [jobId, debouncedQuery]);

  return (
    <div className="relative mb-2">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <Search size={14} className="text-muted-foreground shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search transcript…"
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
        />
        {query && (
          <button
            onClick={() => { setQuery(""); setResults([]); }}
            className="text-muted-foreground hover:text-foreground"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {results.length > 0 && (
        <div className="absolute z-10 top-full left-0 right-0 bg-card border border-border rounded-b-md shadow-lg max-h-64 overflow-y-auto">
          {results.map((r) => (
            <button
              key={r.seq}
              onClick={() => { onSelect?.(r); setQuery(""); setResults([]); }}
              className="w-full text-left px-3 py-2 hover:bg-accent text-sm border-b border-border last:border-0"
            >
              <div className="flex items-center gap-2 text-xs text-muted-foreground mb-0.5">
                <span className="capitalize">{r.role}</span>
                {r.stepNumber != null && <span>· Step {r.stepNumber}</span>}
              </div>
              <div className="truncate text-foreground/90">{r.content}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
