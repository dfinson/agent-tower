import { useStore } from "../store";

/**
 * Shows indexing progress for a specific repository.
 * Renders nothing when the repo is not actively being indexed.
 *
 * The store keys progress by daemon repo name (e.g. "codeplane"),
 * but the Settings screen passes full paths. We try both the full
 * path and the basename as lookup keys.
 */
export function RepoIndexIndicator({ repo }: { repo: string }) {
  const basename = repo.split("/").filter(Boolean).pop() ?? repo;
  const progress = useStore((s) => s.repoIndexState[repo] ?? s.repoIndexState[basename]);
  if (!progress) return null;

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
      <span>
        {progress.phase === "complete" ? "Indexed" : `Indexing ${pct}%`}
      </span>
    </div>
  );
}
