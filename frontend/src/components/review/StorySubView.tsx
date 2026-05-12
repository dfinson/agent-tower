/**
 * Story sub-view — structured review story with header, attention items,
 * concerns, and verdict. Falls back to trail-based narrative when
 * structural enrichment is unavailable.
 *
 * Implements §11 density/edge-case/aggregation rendering:
 * - Edge-case metadata blocks (docs, generated, bulk rename, vendor)
 * - Community rollups when body changes exceed cognitive cap
 * - Pattern groups for repeated structural patterns
 * - Collapsed single-paragraph mode for small jobs
 */
import { useState, useEffect, useCallback } from "react";
import { AlertTriangle, ShieldAlert, ShieldCheck, Shield, CheckCircle, XCircle, ChevronDown, ChevronRight, BookOpen, Lightbulb, RotateCcw, GitBranch, CheckCircle2, RefreshCw } from "lucide-react";
import { fetchReviewStory, fetchJobStory, type ReviewStoryResponse, type EdgeCaseBlock, type PatternGroup } from "../../api/client";
import { useStore } from "../../store";
import { selectReviewStory, selectJobStory } from "../../store/selectors";
import type { StoryResponse, StoryBlock } from "../../api/types";
import { Spinner } from "../ui/spinner";
import { cn } from "../../lib/utils";

interface StorySubViewProps {
  jobId: string;
}

const CONFIDENCE_CONFIG: Record<string, { icon: typeof ShieldCheck; color: string; label: string }> = {
  HIGH: { icon: ShieldCheck, color: "text-green-400", label: "High Confidence" },
  MEDIUM: { icon: Shield, color: "text-yellow-400", label: "Medium Confidence" },
  LOW: { icon: ShieldAlert, color: "text-red-400", label: "Low Confidence" },
};

/** Render a single dependency cycle as a visual chain: A → B → C → A */
function CycleChain({ members }: { members: string[] }) {
  if (members.length === 0) return null;
  // Close the loop by appending the first member
  const display = members.map((m) => m.split("/").pop() ?? m);
  display.push(display[0] ?? "");
  return (
    <div className="flex items-center gap-1 flex-wrap text-[10px] font-mono mt-1">
      {display.map((name, idx) => (
        <span key={idx} className="flex items-center gap-1">
          {idx > 0 && <span className="text-red-400/60">→</span>}
          <span className="text-foreground/80">{name}</span>
        </span>
      ))}
    </div>
  );
}

function StorySection({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{title}</h4>
      <div className="flex flex-col gap-1.5">
        {items.map((item, i) => {
          // §9.8 — Cycle visualization: render cycle paths as visual chains
          const itemType = typeof item.type === "string" ? item.type : "";
          const isCycleItem = itemType === "new_cycles";
          const cycles = isCycleItem && Array.isArray(item.cycles)
            ? (item.cycles as Array<Record<string, unknown>>)
            : [];

          return (
            <div key={i} className={`text-xs text-foreground/90 pl-3 border-l-2 py-1 ${
              isCycleItem ? "border-red-400/50 bg-red-400/5 rounded-r" :
              itemType === "unverified_references" ? "border-yellow-400/50" :
              item.overflow ? "border-muted-foreground/30 italic text-muted-foreground" :
              item.community ? "border-blue-400/40" : "border-border"
            }`}>
              {item.symbol ? (
                <span className="font-mono font-medium">{String(item.symbol)}</span>
              ) : null}
              {item.changeCount ? (
                <span className="text-muted-foreground text-[10px] ml-1">({String(item.changeCount)} changes)</span>
              ) : null}
              {item.summary ? (
                <span className="text-muted-foreground"> &mdash; {String(item.summary)}</span>
              ) : item.detail ? (
                <span className="text-muted-foreground">{String(item.detail)}</span>
              ) : (
                <span className="text-muted-foreground">{JSON.stringify(item)}</span>
              )}
              {item.density && item.density !== "full" && item.density !== "summary" ? (
                <span className="ml-1 text-[10px] text-muted-foreground/60">[{String(item.density)}]</span>
              ) : null}
              {/* §9.8 — Render cycle members as visual path chains */}
              {cycles.map((cycle, ci) => (
                <CycleChain
                  key={ci}
                  members={Array.isArray(cycle.members) ? (cycle.members as string[]) : []}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** §11.5 — Edge-case metadata block (docs, generated, vendor, bulk rename) */
function EdgeCaseSection({ blocks }: { blocks: EdgeCaseBlock[] }) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  if (blocks.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {blocks.map((block, i) => (
        <div key={i} className="rounded border border-border/50 bg-card/50 p-3">
          <button
            className="flex items-center gap-2 w-full text-left"
            onClick={() => setExpanded((prev) => ({ ...prev, [i]: !prev[i] }))}
          >
            <span className="text-sm">{block.icon}</span>
            <span className="text-xs font-medium flex-1">{block.title}</span>
            {expanded[i] ? <ChevronDown size={12} className="text-muted-foreground" /> : <ChevronRight size={12} className="text-muted-foreground" />}
          </button>
          <p className="text-[10px] text-muted-foreground mt-1">{block.detail}</p>
          {expanded[i] && block.files.length > 0 && (
            <div className="mt-2 flex flex-col gap-0.5">
              {block.files.map((f, fi) => (
                <span key={fi} className="text-[10px] font-mono text-muted-foreground pl-2">{f}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** §11.6.2 — Pattern group rendering */
function PatternGroupSection({ groups }: { groups: PatternGroup[] }) {
  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Patterns</h4>
      {groups.map((g, i) => (
        <div key={i} className="text-xs text-foreground/90 pl-3 border-l-2 border-purple-400/40 py-1">
          <span className="font-medium">{g.count} changes</span>
          <span className="text-muted-foreground"> — {g.summary}</span>
        </div>
      ))}
    </div>
  );
}

/** Split text on `backtick` spans and render inline <code> elements. */
function renderInlineCode(text: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          className="font-mono text-[0.85em] text-primary/80 bg-muted/40 px-1 py-px rounded"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

const BEAT_STYLE: Record<string, { icon: typeof Lightbulb; color: string; border: string; label: string }> = {
  decide: { icon: GitBranch, color: "text-blue-400", border: "border-blue-400/40", label: "Decision" },
  backtrack: { icon: RotateCcw, color: "text-amber-400", border: "border-amber-400/40", label: "Course Correction" },
  insight: { icon: Lightbulb, color: "text-emerald-400", border: "border-emerald-400/40", label: "Discovery" },
  verify: { icon: CheckCircle2, color: "text-purple-400", border: "border-purple-400/40", label: "Verification" },
};

/** Render a trail beat as a colored aside block. */
function BeatBlock({ kind, text }: { kind: string; text: string }) {
  const cfg = (BEAT_STYLE[kind] ?? BEAT_STYLE.insight)!;
  const Icon = cfg.icon;
  return (
    <div className={`my-2 pl-3 border-l-2 ${cfg.border} py-1.5`}>
      <div className={`flex items-center gap-1.5 mb-0.5 ${cfg.color}`}>
        <Icon size={11} />
        <span className="text-[10px] font-semibold uppercase tracking-wider">{cfg.label}</span>
      </div>
      <span className="text-sm text-foreground/80 leading-relaxed">{renderInlineCode(text)}</span>
    </div>
  );
}

type Verbosity = "summary" | "standard" | "detailed";

/** Trail-based story fallback when CodeRecon is unavailable. */
function TrailStoryFallback({ jobId }: { jobId: string }) {
  const cachedStory = useStore(selectJobStory(jobId));
  const setStory = useStore((s) => s.setStory);

  const [story, setStoryLocal] = useState<StoryResponse | null>(cachedStory);
  const [loading, setLoading] = useState(cachedStory == null);
  const [error, setError] = useState<string | null>(null);
  const [verbosity, setVerbosity] = useState<Verbosity>("standard");
  const [regenerating, setRegenerating] = useState(false);

  const load = useCallback(
    async (regen = false, verb?: Verbosity) => {
      const v = verb ?? verbosity;
      try {
        if (regen) setRegenerating(true);
        else setLoading(true);
        setError(null);
        const res = await fetchJobStory(jobId, regen, v);
        setStoryLocal(res);
        setStory(jobId, res);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load story";
        setError(msg);
      } finally {
        setLoading(false);
        setRegenerating(false);
      }
    },
    [jobId, verbosity, setStory],
  );

  useEffect(() => {
    if (cachedStory) {
      setStoryLocal(cachedStory);
      setLoading(false);
      return;
    }
    load();
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleVerbosityChange = useCallback(
    (v: Verbosity) => {
      setVerbosity(v);
      load(false, v);
    },
    [load],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
        <AlertTriangle size={16} className="text-yellow-400" />
        <span>{error}</span>
      </div>
    );
  }

  if (!story || story.blocks.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        Not enough data to generate a story yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      <div className="max-w-prose mx-auto w-full rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <BookOpen size={14} className="text-muted-foreground" />
          <h3 className="text-sm font-semibold">Code Review Story</h3>
        </div>
        <div className="text-sm text-muted-foreground leading-relaxed">
          {story.blocks.map((block: StoryBlock, i: number) => {
            if (block.type === "narrative" && block.text) {
              return <span key={`n-${i}`}>{renderInlineCode(block.text)}</span>;
            }
            if (block.type === "beat" && block.text) {
              return <BeatBlock key={`b-${i}`} kind={block.beatKind ?? "insight"} text={block.text} />;
            }
            if (block.type === "reference" && block.file) {
              const fileName = block.file.split("/").pop() ?? "file";
              return (
                <span
                  key={`r-${i}`}
                  className="inline-flex items-center gap-1 mx-0.5 font-mono text-[11px] text-primary/80 bg-muted/30 px-1.5 py-0.5 rounded"
                  title={block.file}
                >
                  {fileName}
                  {block.why && (
                    <span className="text-muted-foreground font-sans"> — {block.why}</span>
                  )}
                </span>
              );
            }
            return null;
          })}
        </div>
        <div className="flex items-center justify-between mt-3 pt-2 border-t border-border/30">
          {/* Verbosity toggle */}
          <div className="flex items-center gap-0.5 bg-muted/30 rounded p-0.5">
            {(["summary", "standard", "detailed"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => handleVerbosityChange(v)}
                className={cn(
                  "px-1.5 py-0.5 text-[9px] font-medium rounded transition-colors",
                  verbosity === v
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground/50 hover:text-muted-foreground",
                )}
              >
                {v === "summary" ? "Brief" : v === "standard" ? "Standard" : "Detailed"}
              </button>
            ))}
          </div>
          <button
            type="button"
            disabled={regenerating}
            onClick={() => load(true)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
          >
            <RefreshCw size={10} className={cn(regenerating && "animate-spin")} />
            {regenerating ? "Regenerating…" : "Regenerate"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function StorySubView({ jobId }: StorySubViewProps) {
  const cached = useStore(selectReviewStory(jobId));
  const setReviewStory = useStore((s) => s.setReviewStory);

  const [data, setData] = useState<ReviewStoryResponse | null>(cached);
  const [loading, setLoading] = useState(cached == null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached != null) {
      setData(cached);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchReviewStory(jobId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setReviewStory(jobId, res);
        }
      })
      .catch((err) => { if (!cancelled) setError(err?.message ?? "Failed to load review story"); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [jobId, cached, setReviewStory]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
        <AlertTriangle size={16} className="text-yellow-400" />
        <span>{error}</span>
      </div>
    );
  }

  // Fallback to trail-based story when CodeRecon review-story is unavailable
  if (!data || !data.available) {
    return <TrailStoryFallback jobId={jobId} />;
  }

  const confidenceCfg = data.header?.mergeConfidence
    ? CONFIDENCE_CONFIG[data.header.mergeConfidence]
    : null;

  // §11.5.6 — Collapsed single-paragraph for small jobs
  if (data.collapsed && data.verdict) {
    return (
      <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
        <div className="max-w-prose mx-auto w-full flex flex-col gap-4">
        {data.header && (
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold">{data.header.title || "Review Story"}</h3>
              {confidenceCfg && (
                <div className={`flex items-center gap-1.5 text-xs font-medium ${confidenceCfg.color}`}>
                  <confidenceCfg.icon size={14} />
                  <span>{confidenceCfg.label}</span>
                </div>
              )}
            </div>
          </div>
        )}
        <div className={`rounded-lg border p-4 ${
          data.verdict.confidence === "HIGH" ? "border-green-400/30 bg-green-400/5" :
          data.verdict.confidence === "LOW" ? "border-red-400/30 bg-red-400/5" :
          "border-yellow-400/30 bg-yellow-400/5"
        }`}>
          <p className="text-xs text-foreground/90">{data.verdict.summary}</p>
        </div>
        {/* Show edge cases even in collapsed mode */}
        <EdgeCaseSection blocks={data.edgeCases ?? []} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 p-4 h-full overflow-y-auto">
      <div className="max-w-prose mx-auto w-full flex flex-col gap-5">
      {/* Header card */}
      {data.header && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold">
              {data.header.title || "Review Story"}
            </h3>
            {confidenceCfg && (
              <div className={`flex items-center gap-1.5 text-xs font-medium ${confidenceCfg.color}`}>
                <confidenceCfg.icon size={14} />
                <span>{confidenceCfg.label}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
            <span>{data.header.fileCount} file{data.header.fileCount !== 1 ? "s" : ""} changed</span>
            {data.header.breakingCount > 0 && (
              <span className="text-red-400">{data.header.breakingCount} breaking</span>
            )}
          </div>
        </div>
      )}

      {/* Attention required */}
      <StorySection title="Needs Attention" items={data.attentionRequired} />

      {/* Structural concerns */}
      <StorySection title="Structural Concerns" items={data.structuralConcerns} />

      {/* What changed — may be community rollups */}
      <StorySection title="What Changed" items={data.whatChanged} />

      {/* Pattern groups (§11.6.2) */}
      <PatternGroupSection groups={data.patternGroups ?? []} />

      {/* What was added */}
      <StorySection title="What Was Added" items={data.whatAdded} />

      {/* Edge-case metadata blocks (§11.5) */}
      <EdgeCaseSection blocks={data.edgeCases ?? []} />

      {/* Non-structural count */}
      {data.nonStructuralCount > 0 && (
        <div className="text-xs text-muted-foreground">
          +{data.nonStructuralCount} non-structural change{data.nonStructuralCount !== 1 ? "s" : ""} (formatting, comments, docs, etc.)
        </div>
      )}

      {/* Verdict */}
      {data.verdict && (
        <div className={`rounded-lg border p-4 ${
          data.verdict.confidence === "HIGH" ? "border-green-400/30 bg-green-400/5" :
          data.verdict.confidence === "LOW" ? "border-red-400/30 bg-red-400/5" :
          "border-yellow-400/30 bg-yellow-400/5"
        }`}>
          <div className="flex items-center gap-2 mb-2">
            {data.verdict.confidence === "HIGH" ? (
              <CheckCircle size={14} className="text-green-400" />
            ) : data.verdict.confidence === "LOW" ? (
              <XCircle size={14} className="text-red-400" />
            ) : (
              <AlertTriangle size={14} className="text-yellow-400" />
            )}
            <span className="text-xs font-semibold">Verdict</span>
          </div>

          {data.verdict.summary && (
            <p className="text-xs text-foreground/90 mb-2">{data.verdict.summary}</p>
          )}

          {data.verdict.blockers.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-medium text-muted-foreground uppercase">Blockers</span>
              {data.verdict.blockers.map((b, i) => (
                <div key={i} className="text-xs text-red-400 pl-2 border-l-2 border-red-400/30">
                  {b}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      </div>
    </div>
  );
}
