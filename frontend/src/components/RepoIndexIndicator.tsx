import { useEffect, useState } from "react";
import { Network, RotateCcw } from "lucide-react";
import { useStore } from "../store";
import { request } from "../api/client";

interface RepoHealth {
  repo: string;
  available: boolean;
  indexStatus: string | null;
  symbolCount: number;
  fileCount: number;
  lastIndexedSha: string | null;
  communityCount: number;
  cycleCount: number;
  stale: boolean;
}

/** Module-level cache so remounts reuse recent data. */
const healthCache = new Map<string, { data: RepoHealth; ts: number }>();
const STALE_MS = 60_000; // refetch after 60 s

/**
 * Shows indexing progress and structural health for a specific repository.
 * Renders nothing when the repo is not actively being indexed and no health data.
 *
 * The store keys progress by daemon repo name (e.g. "codeplane"),
 * but the Settings screen passes full paths. We try both the full
 * path and the basename as lookup keys.
 */
export function RepoIndexIndicator({ repo }: { repo: string }) {
  const basename = repo.split("/").filter(Boolean).pop() ?? repo;
  const progress = useStore((s) => s.repoIndexState[repo] ?? s.repoIndexState[basename]);
  const [health, setHealth] = useState<RepoHealth | null>(() => healthCache.get(repo)?.data ?? null);

  useEffect(() => {
    const cached = healthCache.get(repo);
    if (cached && Date.now() - cached.ts < STALE_MS) {
      setHealth(cached.data);
      return;
    }
    let cancelled = false;
    request<RepoHealth>(`/settings/repos/${encodeURIComponent(repo)}/health`)
      .then((h) => {
        if (!cancelled) {
          setHealth(h);
          healthCache.set(repo, { data: h, ts: Date.now() });
        }
      })
      .catch(() => { /* non-critical */ });
    return () => { cancelled = true; };
  }, [repo]);

  // Show indexing progress when actively indexing
  if (progress && progress.phase !== "complete") {
    const pct = progress.total > 0
      ? Math.round((progress.indexed / progress.total) * 100)
      : 0;
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span>Indexing {pct}%</span>
      </div>
    );
  }

  // Show health summary when available
  if (health?.available) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
        <span title={`${health.symbolCount} symbols, ${health.fileCount} files`}>
          {health.symbolCount > 0 ? `${health.symbolCount} sym` : "Indexed"}
        </span>
        {health.communityCount > 0 && (
          <span className="flex items-center gap-0.5" title={`${health.communityCount} module communities`}>
            <Network size={10} />
            {health.communityCount}
          </span>
        )}
        {health.cycleCount > 0 && (
          <span className="flex items-center gap-0.5 text-amber-400" title={`${health.cycleCount} dependency cycles`}>
            <RotateCcw size={10} />
            {health.cycleCount}
          </span>
        )}
      </div>
    );
  }

  // Show "Indexed" if progress completed but no health data
  if (progress?.phase === "complete") {
    return (
      <span className="text-xs text-muted-foreground">Indexed</span>
    );
  }

  return null;
}
