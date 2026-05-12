import { useCallback, useEffect, useState } from "react";
import { Brain, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { fetchRepoMemory } from "../api/client";
import { Spinner } from "./ui/spinner";

interface KnowledgePanelProps {
  jobId: string;
  repoPath: string;
}

export function KnowledgePanel({ repoPath }: KnowledgePanelProps) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [memory, setMemory] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchRepoMemory(repoPath);
      setMemory(res.memory);
    } catch {
      setMemory("");
    } finally {
      setLoading(false);
    }
  }, [repoPath]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner className="w-5 h-5" />
      </div>
    );
  }

  if (!memory) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
        <Brain size={32} className="text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">
          No workspace memory yet for this repository.
        </p>
        <p className="text-xs text-muted-foreground/70 max-w-sm">
          As the agent works, it accumulates decisions, patterns, and lessons learned.
          Memory grows automatically across jobs.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-4 overflow-y-auto max-h-[calc(100dvh-140px)] md:max-h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-muted-foreground" />
          <h3 className="text-sm font-medium text-foreground">Workspace Memory</h3>
        </div>
        <button
          onClick={() => navigate(`/repos/${encodeURIComponent(repoPath)}/memory`)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <span>Edit</span>
          <ExternalLink size={12} />
        </button>
      </div>
      <div className="rounded-lg border border-border bg-background/50 p-4">
        <pre className="text-sm text-foreground/90 whitespace-pre-wrap font-mono leading-relaxed">
          {memory}
        </pre>
      </div>
    </div>
  );
}
