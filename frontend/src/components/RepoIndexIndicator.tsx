import { useStore } from "../store";

/**
 * Shows indexing progress for a specific repository.
 * Renders nothing when the repo is not actively being indexed.
 */
export function RepoIndexIndicator({ repo }: { repo: string }) {
  const progress = useStore((s) => s.repoIndexState[repo]);
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
