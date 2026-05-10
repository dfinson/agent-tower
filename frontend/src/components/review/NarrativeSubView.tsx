/**
 * NarrativeSubView — agent cognitive journey.
 *
 * Renders the chronological narrative assembled from trail enrichment
 * data: decisions, backtracks, insights, and verifications. Uses colored
 * left-border blocks for beat asides.
 */
import { useEffect, useState } from "react";
import { Lightbulb, RotateCcw, GitFork, ShieldCheck, BookOpen } from "lucide-react";
import { fetchNarrative, type NarrativeResponse, type NarrativeBlock } from "../../api/client";
import { Spinner } from "../ui/spinner";

interface NarrativeSubViewProps {
  jobId: string;
}

const BEAT_CONFIG: Record<string, { icon: typeof Lightbulb; color: string; border: string; bg: string; label: string }> = {
  decide: { icon: GitFork, color: "text-blue-400", border: "border-blue-400/50", bg: "bg-blue-400/5", label: "Decision" },
  backtrack: { icon: RotateCcw, color: "text-amber-400", border: "border-amber-400/50", bg: "bg-amber-400/5", label: "Backtrack" },
  insight: { icon: Lightbulb, color: "text-emerald-400", border: "border-emerald-400/50", bg: "bg-emerald-400/5", label: "Insight" },
  verify: { icon: ShieldCheck, color: "text-purple-400", border: "border-purple-400/50", bg: "bg-purple-400/5", label: "Verification" },
};

function BeatBlock({ block }: { block: NarrativeBlock }) {
  const kind = block.beatKind ?? "decide";
  // Default to "decide" config — always defined in BEAT_CONFIG
  const cfg = (BEAT_CONFIG[kind] ?? BEAT_CONFIG["decide"])!;
  const Icon = cfg.icon;

  return (
    <div className={`pl-3 py-2 border-l-2 rounded-r ${cfg.border} ${cfg.bg}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={12} className={cfg.color} />
        <span className={`text-[10px] font-semibold uppercase tracking-wider ${cfg.color}`}>{cfg.label}</span>
      </div>
      <p className="text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap">{block.text}</p>
      {block.files && block.files.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {block.files.map((f, i) => (
            <span key={i} className="text-[10px] font-mono text-muted-foreground bg-muted/50 px-1 py-0.5 rounded">
              {f.split("/").pop()}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ProseBlock({ block }: { block: NarrativeBlock }) {
  return (
    <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">{block.text}</p>
  );
}

function LedeBlock({ block }: { block: NarrativeBlock }) {
  return (
    <div className="pb-3 mb-3 border-b border-border">
      <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">{block.text}</p>
    </div>
  );
}

function OutcomeBlock({ block }: { block: NarrativeBlock }) {
  return (
    <div className="pt-3 mt-3 border-t border-border">
      <p className="text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap italic">{block.text}</p>
    </div>
  );
}

function NarrativeBlockRenderer({ block }: { block: NarrativeBlock }) {
  switch (block.type) {
    case "lede": return <LedeBlock block={block} />;
    case "beat": return <BeatBlock block={block} />;
    case "outcome": return <OutcomeBlock block={block} />;
    default: return <ProseBlock block={block} />;
  }
}

export function NarrativeSubView({ jobId }: NarrativeSubViewProps) {
  const [data, setData] = useState<NarrativeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchNarrative(jobId)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(e?.message ?? "Failed to load narrative"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [jobId]);

  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-xs text-red-400">
        <span>Failed to generate narrative: {error}</span>
      </div>
    );
  }

  if (!data || data.blocks.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-muted-foreground">
        <BookOpen size={20} />
        <p className="text-xs">No trail data available for narrative generation.</p>
      </div>
    );
  }

  return (
    <div className="px-4 py-3 max-w-2xl mx-auto flex flex-col gap-3">
      {/* Beat summary bar */}
      {data.beatCount > 0 && (
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
          <span>{data.beatCount} beat{data.beatCount !== 1 ? "s" : ""}</span>
          {data.hasDecisions && <span className="text-blue-400">decisions</span>}
          {data.hasBacktracks && <span className="text-amber-400">backtracks</span>}
        </div>
      )}

      {/* Narrative blocks */}
      {data.blocks.map((block, i) => (
        <NarrativeBlockRenderer key={i} block={block} />
      ))}
    </div>
  );
}
