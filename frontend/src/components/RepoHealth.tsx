import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Boxes, AlertTriangle, FileCode, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Spinner } from "./ui/spinner";
import { Button } from "./ui/button";
import { request } from "../api/client";

interface HealthData {
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

function fetchHealth(repoPath: string): Promise<HealthData> {
  return request<HealthData>(`/settings/repos/${encodeURIComponent(repoPath)}/health`);
}

export function RepoHealth() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";
  const repoName = decoded.split("/").pop() || decoded;

  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<HealthData | null>(null);

  const load = useCallback(async () => {
    if (!decoded) return;
    setLoading(true);
    try {
      const res = await fetchHealth(decoded);
      setHealth(res);
    } catch {
      toast.error("Failed to load health data");
    } finally {
      setLoading(false);
    }
  }, [decoded]);

  useEffect(() => {
    let ignore = false;
    if (!decoded) return;
    setLoading(true);
    fetchHealth(decoded)
      .then((res) => { if (!ignore) setHealth(res); })
      .catch(() => { if (!ignore) toast.error("Failed to load health data"); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [decoded]); // eslint-disable-line react-hooks/exhaustive-deps

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
            <Boxes size={16} className="text-muted-foreground" />
            Structural Health
          </h1>
          <p className="text-sm text-muted-foreground truncate">{repoName}</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Spinner size="lg" />
        </div>
      ) : !health || !health.available ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <Boxes size={32} className="mx-auto mb-3 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            CodeRecon is not available for this repository.
          </p>
          {health?.indexStatus === "error" && (
            <p className="text-xs text-red-400 mt-2">Index error occurred</p>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-border bg-card p-5 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <FileCode size={14} className="text-muted-foreground" />
              Codebase Size
            </div>
            <div className="grid grid-cols-2 gap-4 pt-2">
              <div>
                <p className="text-2xl font-bold text-foreground">{health.symbolCount.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Symbols</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-foreground">{health.fileCount.toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Files</p>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-5 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Boxes size={14} className="text-muted-foreground" />
              Structure
            </div>
            <div className="grid grid-cols-2 gap-4 pt-2">
              <div>
                <p className="text-2xl font-bold text-foreground">{health.communityCount}</p>
                <p className="text-xs text-muted-foreground">Communities</p>
              </div>
              <div>
                <p className={`text-2xl font-bold ${health.cycleCount > 0 ? "text-yellow-400" : "text-foreground"}`}>
                  {health.cycleCount}
                </p>
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  Dependency Cycles
                  {health.cycleCount > 0 && <AlertTriangle size={10} className="text-yellow-400" />}
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-5 space-y-2 md:col-span-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              Index Status
            </div>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span>
                Status: <span className="text-foreground font-medium">{health.indexStatus || "unknown"}</span>
              </span>
              {health.lastIndexedSha && (
                <span>
                  Last SHA: <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{health.lastIndexedSha.slice(0, 12)}</code>
                </span>
              )}
              {health.stale && (
                <span className="text-yellow-400 flex items-center gap-1">
                  <AlertTriangle size={12} />
                  Stale
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
