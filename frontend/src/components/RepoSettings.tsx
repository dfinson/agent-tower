import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Settings, GitBranch, Globe } from "lucide-react";
import { toast } from "sonner";
import { fetchRepoDetail } from "../api/client";
import type { RepoDetailResponse } from "../api/types";
import { RepoIndexIndicator } from "./RepoIndexIndicator";
import { Spinner } from "./ui/spinner";

export function RepoSettings() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";
  const repoName = decoded.split("/").pop() || decoded;

  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<RepoDetailResponse | null>(null);

  const load = useCallback(async () => {
    if (!decoded) return;
    setLoading(true);
    try {
      const res = await fetchRepoDetail(decoded);
      setDetail(res);
    } catch {
      toast.error("Failed to load repository details");
    } finally {
      setLoading(false);
    }
  }, [decoded]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link
          to={`/repos/${encodeURIComponent(decoded)}`}
          className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Back to overview"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Settings size={16} className="text-muted-foreground" />
            Repository Settings
          </h1>
          <p className="text-sm text-muted-foreground truncate">{repoName}</p>
        </div>
      </div>

      {!detail ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground">
          Repository details unavailable
        </div>
      ) : (
        <div className="space-y-4">
          {/* Repository Info */}
          <div className="rounded-lg border border-border bg-card p-5 space-y-4">
            <h3 className="text-sm font-semibold">Repository Information</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Path</p>
                <p className="font-mono text-xs text-foreground break-all">{detail.path}</p>
              </div>
              {detail.originUrl && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <Globe size={10} /> Origin URL
                  </p>
                  <p className="font-mono text-xs text-foreground break-all">{detail.originUrl}</p>
                </div>
              )}
              {detail.baseBranch && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <GitBranch size={10} /> Default Branch
                  </p>
                  <p className="text-foreground">{detail.baseBranch}</p>
                </div>
              )}
              {detail.currentBranch && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <GitBranch size={10} /> Current Branch
                  </p>
                  <p className="text-foreground">{detail.currentBranch}</p>
                </div>
              )}
              {detail.platform && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Platform</p>
                  <p className="text-foreground capitalize">{detail.platform}</p>
                </div>
              )}
            </div>
          </div>

          {/* Index Status */}
          <div className="rounded-lg border border-border bg-card p-5 space-y-3">
            <h3 className="text-sm font-semibold">Index Status</h3>
            <div className="flex items-center gap-3">
              <RepoIndexIndicator repo={decoded} />
              <span className="text-sm text-muted-foreground">
                {detail.activeJobCount ?? 0} active jobs using this repository
              </span>
            </div>
          </div>

          {/* Per-repo settings placeholder */}
          <div className="rounded-lg border border-dashed border-border bg-card/50 p-5 space-y-2">
            <h3 className="text-sm font-semibold text-muted-foreground">Per-Repository Overrides</h3>
            <p className="text-xs text-muted-foreground">
              Per-repository settings (auto-push, max turns, branch config, self-review) will be available here in a future release.
              Currently, these are configured globally in Settings.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
