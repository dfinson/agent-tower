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
import React, { useState, useEffect, useCallback } from "react";
import { AlertTriangle, ShieldAlert, ShieldCheck, Shield, ChevronDown, ChevronRight, BookOpen, RefreshCw } from "lucide-react";
import { fetchReviewStory, fetchJobStory, type ReviewStoryResponse, type EdgeCaseBlock, type PatternGroup } from "../../api/client";
import { useStore } from "../../store";
import { selectReviewStory, selectJobStory } from "../../store/selectors";
import type { StoryBlock } from "../../api/types";
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
            <div key={i} className={`text-xs text-foreground/90 pl-3 border-l-2 py-1 min-w-0 break-words ${
              isCycleItem ? "border-red-400/50 bg-red-400/5 rounded-r" :
              itemType === "unverified_references" ? "border-yellow-400/50" :
              item.overflow ? "border-muted-foreground/30 italic text-muted-foreground" :
              item.community ? "border-blue-400/40" : "border-border"
            }`}>
              {item.symbol ? (
                <span className="font-mono font-medium break-all">{String(item.symbol)}</span>
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
          className="font-mono text-[0.85em] text-primary/80 bg-muted/40 px-1 py-px rounded break-all"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

/** Split block text on double-newlines into separate <p> elements. */
function renderParagraphs(text: string, keyPrefix: string): React.ReactNode[] {
  const paragraphs = text.split(/\n\n+/).filter(Boolean);
  return paragraphs.map((p, i) => (
    <p key={`${keyPrefix}-p${i}`} className="m-0">{renderInlineCode(p.trim())}</p>
  ));
}

/** Render a unified diff snippet with add/remove line highlighting. */
function DiffCard({ file, snippet }: { file: string; snippet: string }) {
  // Strip the "diff --git" header and "---/+++" lines, keep only hunks
  const lines = snippet.split("\n");
  const hunkLines: string[] = [];
  let inHunk = false;
  for (const line of lines) {
    if (line.startsWith("@@")) {
      inHunk = true;
      hunkLines.push(line);
    } else if (inHunk) {
      hunkLines.push(line);
    }
  }
  const displayLines = hunkLines.length > 0 ? hunkLines : lines;

  return (
    <div className="rounded border border-border/50 bg-muted/20 overflow-hidden my-2">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/30 border-b border-border/30 min-w-0">
        <span className="font-mono text-[11px] text-primary/80 truncate min-w-0">{file}</span>
      </div>
      <pre className="px-0 py-1 font-mono text-[11px] overflow-x-auto whitespace-pre m-0">
        {displayLines.map((line, i) => {
          let cls = "text-foreground/60 px-3";
          if (line.startsWith("+") && !line.startsWith("+++")) {
            cls = "text-green-400/90 bg-green-400/10 px-3";
          } else if (line.startsWith("-") && !line.startsWith("---")) {
            cls = "text-red-400/90 bg-red-400/10 px-3";
          } else if (line.startsWith("@@")) {
            cls = "text-blue-400/60 px-3";
          }
          return <div key={i} className={cls}>{line || " "}</div>;
        })}
      </pre>
    </div>
  );
}

/** Build a categorized file overview from story blocks. */
function StoryTOC({ blocks }: { blocks: StoryBlock[] }) {
  const refs = blocks.filter(
    (b): b is StoryBlock & { file: string } => b.type === "reference" && !!b.file,
  );
  if (refs.length === 0) return null;

  // Deduplicate: keep first occurrence of each file
  const seen = new Set<string>();
  const unique: Array<{ file: string; action: "created" | "modified" | "read" }> = [];
  for (const r of refs) {
    if (!seen.has(r.file)) {
      seen.add(r.file);
      unique.push({ file: r.file, action: r.action ?? "modified" });
    }
  }

  const created = unique.filter((u) => u.action === "created");
  const modified = unique.filter((u) => u.action === "modified");
  const read = unique.filter((u) => u.action === "read");

  const FileList = ({ items, label, color }: { items: typeof unique; label: string; color: string }) => {
    if (items.length === 0) return null;
    return (
      <div className="flex items-start gap-2 min-w-0">
        <span className={`text-[10px] font-semibold uppercase tracking-wider shrink-0 mt-px ${color}`}>
          {label}
        </span>
        <div className="flex flex-wrap gap-x-2 gap-y-1 min-w-0">
          {items.map((u) => (
            <span
              key={u.file}
              className="font-mono text-[11px] text-primary/70 bg-muted/30 px-1.5 py-0.5 rounded break-all"
            >
              {u.file}
            </span>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="border border-border/30 rounded-md bg-muted/10 p-3 mb-2 flex flex-col gap-2">
      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
        Files &middot; {unique.length}
      </span>
      <FileList items={modified} label="Modified" color="text-yellow-500/80" />
      <FileList items={created} label="Created" color="text-green-500/80" />
      <FileList items={read} label="Read" color="text-blue-500/80" />
    </div>
  );
}

type Verbosity = "summary" | "standard" | "detailed";

/** Trail-based story fallback when CodeRecon is unavailable. */
function TrailStoryFallback({ jobId }: { jobId: string }) {
  const setStory = useStore((s) => s.setStory);

  const [verbosity, setVerbosity] = useState<Verbosity>("standard");
  const [regenerating, setRegenerating] = useState(false);
  const [errors, setErrors] = useState<Record<Verbosity, string | null>>({
    summary: null, standard: null, detailed: null,
  });

  // Per-verbosity cache from store
  const cachedSummary = useStore(selectJobStory(jobId, "summary"));
  const cachedStandard = useStore(selectJobStory(jobId, "standard"));
  const cachedDetailed = useStore(selectJobStory(jobId, "detailed"));

  const storyForVerbosity = (v: Verbosity) => {
    if (v === "summary") return cachedSummary;
    if (v === "detailed") return cachedDetailed;
    return cachedStandard;
  };

  const story = storyForVerbosity(verbosity);

  // Track which levels are being fetched
  const [fetching, setFetching] = useState<Record<Verbosity, boolean>>({
    summary: false, standard: false, detailed: false,
  });

  const fetchLevel = useCallback(
    async (v: Verbosity, regen = false) => {
      setFetching((prev) => ({ ...prev, [v]: true }));
      try {
        const res = await fetchJobStory(jobId, regen, v);
        // Don't cache empty responses — they poison the store and
        // block future attempts to generate the story.
        if (res.blocks && res.blocks.length > 0) {
          setStory(jobId, res);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Failed to load story";
        setErrors((prev) => ({ ...prev, [v]: msg }));
      } finally {
        setFetching((prev) => ({ ...prev, [v]: false }));
      }
    },
    [jobId, setStory],
  );

  // Eagerly fetch all verbosity levels on mount
  useEffect(() => {
    const levels: Verbosity[] = ["summary", "standard", "detailed"];
    for (const v of levels) {
      if (!storyForVerbosity(v)) {
        fetchLevel(v);
      }
    }
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleVerbosityChange = useCallback(
    (v: Verbosity) => {
      setVerbosity(v);
      setErrors((prev) => ({ ...prev, [v]: null }));
      // If this verbosity level isn't cached, trigger a fetch
      const cached = v === "summary" ? cachedSummary : v === "detailed" ? cachedDetailed : cachedStandard;
      if (!cached) {
        fetchLevel(v);
      }
    },
    [fetchLevel, cachedSummary, cachedStandard, cachedDetailed],
  );

  const handleRegenerate = useCallback(() => {
    setRegenerating(true);
    setErrors((prev) => ({ ...prev, [verbosity]: null }));
    fetchLevel(verbosity, true).finally(() => setRegenerating(false));
  }, [fetchLevel, verbosity]);

  // Show loading only if the currently selected verbosity is being fetched
  const loading = fetching[verbosity] && !story;
  const hasStory = story && story.blocks.length > 0;
  const error = errors[verbosity];

  // Wrap the verbosity toggle + regenerate so they're always visible,
  // even when the story content area shows loading/error/empty.
  const controls = (
    <div className="flex items-center justify-between mt-3 pt-2 border-t border-border/30">
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
        onClick={handleRegenerate}
        className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        <RefreshCw size={10} className={cn(regenerating && "animate-spin")} />
        {regenerating ? "Regenerating\u2026" : "Regenerate"}
      </button>
    </div>
  );

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-center h-48">
          <Spinner size="md" />
        </div>
        {controls}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
          <AlertTriangle size={16} className="text-yellow-400" />
          <span>{error}</span>
        </div>
        {controls}
      </div>
    );
  }

  if (!hasStory) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col items-center justify-center h-48 gap-3 text-sm text-muted-foreground">
          <p>Story generation returned no content for this level.</p>
          <button
            type="button"
            disabled={regenerating}
            onClick={handleRegenerate}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
          >
            <RefreshCw size={12} className={cn(regenerating && "animate-spin")} />
            {regenerating ? "Generating\u2026" : "Try generating"}
          </button>
        </div>
        {controls}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 overflow-hidden min-w-0">
      <div className="flex items-center gap-2 mb-3">
        <BookOpen size={14} className="text-muted-foreground" />
        <h3 className="text-sm font-semibold">Code Review Story</h3>
      </div>
        <StoryTOC blocks={story.blocks} />
        <div className="text-sm text-foreground/80 leading-relaxed flex flex-col gap-3 min-w-0 break-words">
          {story.blocks.map((block: StoryBlock, i: number) => {
            if (block.type === "heading" && block.text) {
              return (
                <h4
                  key={`h-${i}`}
                  className={cn(
                    "text-sm font-semibold text-foreground/90 pt-4 pb-1",
                    i > 0 && "border-t border-border/20 mt-2",
                  )}
                >
                  {block.text}
                </h4>
              );
            }
            if ((block.type === "narrative" || block.type === "beat") && block.text) {
              return (
                <React.Fragment key={`t-${i}`}>
                  {renderParagraphs(block.text, `t-${i}`)}
                </React.Fragment>
              );
            }
            if (block.type === "reference" && block.file && block.snippet) {
              return <DiffCard key={`r-${i}`} file={block.file} snippet={block.snippet} />;
            }
            return null;
          })}
        </div>
        {controls}
      </div>
  );
}

/** Compact structural review card — shown above the narrative when CodeRecon data is available.
 *  Only surfaces content that warrants attention: breaking changes, structural concerns,
 *  blockers. For clean jobs, shows a single-line verdict. */
function StructuralReviewCard({ data }: { data: ReviewStoryResponse }) {
  const [expanded, setExpanded] = useState(false);
  const confidenceCfg = data.header?.mergeConfidence
    ? CONFIDENCE_CONFIG[data.header.mergeConfidence]
    : null;

  const hasAttention = data.attentionRequired.length > 0;
  const hasConcerns = data.structuralConcerns.length > 0;
  const hasBlockers = (data.verdict?.blockers.length ?? 0) > 0;
  const hasDetail = hasAttention || hasConcerns || hasBlockers
    || data.whatChanged.length > 0 || (data.edgeCases ?? []).length > 0;

  const borderColor = data.verdict?.confidence === "HIGH" ? "border-green-400/30" :
    data.verdict?.confidence === "LOW" ? "border-red-400/30" : "border-yellow-400/30";
  const bgColor = data.verdict?.confidence === "HIGH" ? "bg-green-400/5" :
    data.verdict?.confidence === "LOW" ? "bg-red-400/5" : "bg-yellow-400/5";

  return (
    <div className={`rounded-lg border ${borderColor} ${bgColor} p-3 overflow-hidden min-w-0`}>
      {/* Header line: confidence + file count + verdict */}
      <div className="flex items-center gap-3 min-w-0 flex-wrap">
        {confidenceCfg && (
          <div className={`flex items-center gap-1 text-xs font-medium ${confidenceCfg.color}`}>
            <confidenceCfg.icon size={13} />
            <span>{confidenceCfg.label}</span>
          </div>
        )}
        {data.header && (
          <span className="text-[10px] text-muted-foreground">
            {data.header.fileCount} file{data.header.fileCount !== 1 ? "s" : ""}
            {data.header.breakingCount > 0 && (
              <span className="text-red-400 ml-1">{data.header.breakingCount} breaking</span>
            )}
          </span>
        )}
        <span className="flex-1" />
        {hasDetail && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
          >
            {expanded ? "Hide details" : "Show details"}
          </button>
        )}
      </div>

      {/* Verdict summary */}
      {data.verdict?.summary && (
        <p className="text-xs text-foreground/80 mt-1 break-words">{data.verdict.summary}</p>
      )}

      {/* Blockers — always visible if present */}
      {hasBlockers && data.verdict && (
        <div className="flex flex-col gap-1 mt-2">
          {data.verdict.blockers.map((b, i) => (
            <div key={i} className="text-xs text-red-400 pl-2 border-l-2 border-red-400/30 break-words">
              {b}
            </div>
          ))}
        </div>
      )}

      {/* Expanded detail sections */}
      {expanded && (
        <div className="mt-3 pt-2 border-t border-border/30 flex flex-col gap-3">
          <StorySection title="Needs Attention" items={data.attentionRequired} />
          <StorySection title="Structural Concerns" items={data.structuralConcerns} />
          <StorySection title="What Changed" items={data.whatChanged} />
          <PatternGroupSection groups={data.patternGroups ?? []} />
          <StorySection title="What Was Added" items={data.whatAdded} />
          <EdgeCaseSection blocks={data.edgeCases ?? []} />
          {data.nonStructuralCount > 0 && (
            <div className="text-xs text-muted-foreground">
              +{data.nonStructuralCount} non-structural change{data.nonStructuralCount !== 1 ? "s" : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function StorySubView({ jobId }: StorySubViewProps) {
  // Fetch structural review data in parallel (for the summary card)
  const cachedReview = useStore(selectReviewStory(jobId));
  const setReviewStory = useStore((s) => s.setReviewStory);
  const [reviewData, setReviewData] = useState<ReviewStoryResponse | null>(cachedReview);

  useEffect(() => {
    if (cachedReview != null) {
      setReviewData(cachedReview);
      return;
    }
    let cancelled = false;
    fetchReviewStory(jobId)
      .then((res) => { if (!cancelled) { setReviewData(res); setReviewStory(jobId, res); } })
      .catch(() => { /* structural data is optional */ })
    return () => { cancelled = true; };
  }, [jobId, cachedReview, setReviewStory]);

  const showStructural = reviewData?.available && (
    reviewData.header != null || reviewData.verdict != null
  );

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto w-full flex flex-col gap-4">
        {/* Structural review card — compact verdict from CodeRecon */}
        {showStructural && <StructuralReviewCard data={reviewData!} />}

        {/* Agent narrative — the actual story */}
        <TrailStoryFallback jobId={jobId} />
      </div>
    </div>
  );
}
