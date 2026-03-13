import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Card, CardHeader, CardTitle, CardContent } from "../ui/Card";
import { Button } from "../ui/Button";
import { Spinner, EmptyState } from "../ui/Feedback";
import { toast } from "sonner";

interface RepoDetail {
  path: string;
  originUrl: string | null;
  baseBranch: string | null;
  activeJobCount?: number;
}

export function RepositoryDetailView() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<RepoDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!repoPath) return;
    fetch(`/api/settings/repos/${encodeURIComponent(repoPath)}`)
      .then((r) => r.json())
      .then(setDetail)
      .catch(() => toast.error("Failed to load repo details"))
      .finally(() => setLoading(false));
  }, [repoPath]);

  if (loading) return <Spinner />;
  if (!detail) return <EmptyState text="Repository not found" />;

  return (
    <div className="max-w-3xl mx-auto">
      <Button variant="ghost" size="sm" onClick={() => navigate("/settings")} className="mb-4">
        ← Back to Settings
      </Button>
      <Card>
        <CardHeader>
          <CardTitle>{detail.path.split("/").pop()}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-sm">
            <div>
              <span className="text-text-dim text-xs uppercase tracking-wide">Path</span>
              <div className="font-mono text-text-muted">{detail.path}</div>
            </div>
            {detail.originUrl && (
              <div>
                <span className="text-text-dim text-xs uppercase tracking-wide">Origin</span>
                <div className="text-text-muted">{detail.originUrl}</div>
              </div>
            )}
            {detail.baseBranch && (
              <div>
                <span className="text-text-dim text-xs uppercase tracking-wide">Base Branch</span>
                <div className="text-text-muted">{detail.baseBranch}</div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
