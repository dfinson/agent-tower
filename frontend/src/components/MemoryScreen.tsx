import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Archive, Save, Sparkles } from "lucide-react";
import { toast } from "sonner";
import {
  fetchRepoMemoryDetail,
  updateRepoMemory,
  compactRepoMemory,
} from "../api/client";
import type { MemoryDetailResponse } from "../api/client";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { Spinner } from "./ui/spinner";

export function MemoryScreen() {
  const { repoPath } = useParams<{ repoPath: string }>();
  const navigate = useNavigate();
  const decoded = repoPath ? decodeURIComponent(repoPath) : "";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [decisions, setDecisions] = useState("");
  const [wisdom, setWisdom] = useState("");
  const [archive, setArchive] = useState("");
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    if (!decoded) return;
    setLoading(true);
    try {
      const detail: MemoryDetailResponse = await fetchRepoMemoryDetail(decoded);
      setDecisions(detail.decisions);
      setWisdom(detail.wisdom);
      setArchive(detail.archive);
      setDirty(false);
    } catch (err) {
      toast.error("Failed to load memory");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [decoded]);

  useEffect(() => { load(); }, [load]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateRepoMemory(decoded, { decisions, wisdom });
      setDirty(false);
      toast.success("Memory saved");
    } catch (err) {
      toast.error("Failed to save memory");
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleCompact = async () => {
    setCompacting(true);
    try {
      const res = await compactRepoMemory(decoded);
      if (res.compacted) {
        toast.success("Decisions compacted into archive");
        await load();
      } else {
        toast("Nothing to compact — decisions are below threshold");
      }
    } catch (err) {
      toast.error("Compaction failed");
      console.error(err);
    } finally {
      setCompacting(false);
    }
  };

  const repoName = decoded.split("/").pop() || decoded;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner className="w-6 h-6" />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-md hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Go back"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold text-foreground truncate">
            Repository Memory
          </h1>
          <p className="text-sm text-muted-foreground truncate">{repoName}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleCompact}
            disabled={compacting || !decisions}
          >
            {compacting ? <Spinner className="w-3.5 h-3.5 mr-1.5" /> : <Sparkles size={14} className="mr-1.5" />}
            Compact
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving || !dirty}
          >
            {saving ? <Spinner className="w-3.5 h-3.5 mr-1.5" /> : <Save size={14} className="mr-1.5" />}
            Save
          </Button>
        </div>
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Decisions */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Decisions
          </label>
          <p className="text-xs text-muted-foreground">
            Patterns, conventions, and choices the agent should follow.
          </p>
          <Textarea
            value={decisions}
            onChange={(e) => { setDecisions(e.target.value); setDirty(true); }}
            className="min-h-[300px] font-mono text-sm resize-y"
            placeholder="No decisions recorded yet. The agent will accumulate patterns here as it works."
          />
        </div>

        {/* Wisdom */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-foreground">
            Wisdom
          </label>
          <p className="text-xs text-muted-foreground">
            Gotchas, lessons learned, and environment-specific knowledge.
          </p>
          <Textarea
            value={wisdom}
            onChange={(e) => { setWisdom(e.target.value); setDirty(true); }}
            className="min-h-[300px] font-mono text-sm resize-y"
            placeholder="No wisdom recorded yet. The agent will capture lessons learned here."
          />
        </div>
      </div>

      {/* Archive (collapsible) */}
      {archive && (
        <div className="border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => setArchiveOpen(!archiveOpen)}
            className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          >
            <Archive size={14} />
            <span>Archive</span>
            <span className="text-xs text-muted-foreground/70 ml-auto">
              {archive.length.toLocaleString()} chars
            </span>
          </button>
          {archiveOpen && (
            <div className="px-4 pb-4">
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono bg-background/50 rounded-md p-3 max-h-64 overflow-y-auto">
                {archive}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Stats footer */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground/70 pt-2 border-t border-border">
        <span>Decisions: {decisions.length.toLocaleString()} chars</span>
        <span>Wisdom: {wisdom.length.toLocaleString()} chars</span>
        {archive && <span>Archive: {archive.length.toLocaleString()} chars</span>}
      </div>
    </div>
  );
}
