/**
 * StoryBanner — collapsible code-review narrative embedded in the DiffViewer.
 *
 * Renders the LLM-generated story with change references as small inline
 * filename links. Clicking a link selects that file in the diff sidebar.
 */

import { useEffect, useState, useCallback } from "react";
import { BookOpen, ChevronDown, RefreshCw, Lightbulb, RotateCcw, GitBranch, CheckCircle2 } from "lucide-react";
import { fetchJobStory } from "../api/client";
import { useStore, selectJobStory } from "../store";
import type { StoryBlock, DiffFileModel } from "../api/types";
import { InlineDiffBlock } from "./InlineDiffBlock";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";

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

type Verbosity = "summary" | "standard" | "detailed";

const BEAT_CONFIG: Record<string, { icon: typeof Lightbulb; color: string; border: string; label: string }> = {
  decide: { icon: GitBranch, color: "text-blue-400", border: "border-blue-400/40", label: "Decision" },
  backtrack: { icon: RotateCcw, color: "text-amber-400", border: "border-amber-400/40", label: "Course Correction" },
  insight: { icon: Lightbulb, color: "text-emerald-400", border: "border-emerald-400/40", label: "Discovery" },
  verify: { icon: CheckCircle2, color: "text-purple-400", border: "border-purple-400/40", label: "Verification" },
};

/** Render a trail beat as a colored aside block. */
function BeatBlock({ kind, text }: { kind: string; text: string }) {
  const cfg = (BEAT_CONFIG[kind] ?? BEAT_CONFIG.insight)!;
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

interface StoryBannerProps {
  jobId: string;
  diffs: DiffFileModel[];
  onSelectFile: (idx: number) => void;
}

/** Find the index of a file in diffs by matching the tail of the path. */
function findFileIdx(diffs: DiffFileModel[], file: string): number {
  // Try exact match first
  let idx = diffs.findIndex((d) => d.path === file);
  if (idx >= 0) return idx;
  // Try tail match — story paths are absolute, diff paths are relative
  idx = diffs.findIndex((d) => file.endsWith("/" + d.path) || file.endsWith(d.path));
  if (idx >= 0) return idx;
  // Try basename match as last resort
  const basename = file.split("/").pop() ?? "";
  return diffs.findIndex((d) => d.path.split("/").pop() === basename);
}

/** Smart default verbosity based on file count. */
function defaultVerbosity(fileCount: number): Verbosity {
  if (fileCount <= 3) return "detailed";
  if (fileCount >= 10) return "summary";
  return "standard";
}

// ---------------------------------------------------------------------------
// Banner
// ---------------------------------------------------------------------------

export function StoryBanner({ jobId, diffs, onSelectFile }: StoryBannerProps) {
  const setStory = useStore((s) => s.setStory);
  const [open, setOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [verbosity, setVerbosity] = useState<Verbosity>(() => defaultVerbosity(diffs.length));

  // Per-verbosity cached stories from store
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
        const data = await fetchJobStory(jobId, regen, v);
        setStory(jobId, data);
      } catch {
        // Silently ignore background fetch failures
      } finally {
        setFetching((prev) => ({ ...prev, [v]: false }));
      }
    },
    [jobId, setStory],
  );

  // Eagerly fetch all verbosity levels when banner is opened
  useEffect(() => {
    if (!open) return;
    const levels: Verbosity[] = ["summary", "standard", "detailed"];
    for (const v of levels) {
      if (!storyForVerbosity(v)) {
        fetchLevel(v);
      }
    }
  }, [open, jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleVerbosityChange = useCallback(
    (v: Verbosity) => {
      setVerbosity(v);
    },
    [],
  );

  const loading = fetching[verbosity] && !story;

  const hasStory = story && story.blocks.length > 0;

  /** Handle ref click — resolve file index and select it. */
  const handleRefClick = useCallback(
    (block: StoryBlock) => {
      if (!block.file) return;
      const idx = findFileIdx(diffs, block.file);
      if (idx >= 0) onSelectFile(idx);
    },
    [diffs, onSelectFile],
  );

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-accent/30 transition-colors"
      >
        <BookOpen size={13} className="text-muted-foreground shrink-0" />
        <span className="text-xs font-medium text-muted-foreground flex-1">Story</span>
        <ChevronDown
          size={13}
          className={cn(
            "text-muted-foreground/50 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="border-t border-border/40 px-3 py-2.5">
          {loading && (
            <div className="flex items-center gap-2 py-2 text-muted-foreground">
              <Spinner />
              <span className="text-xs">Generating story…</span>
            </div>
          )}

          {!hasStory && !loading && (
            <p className="text-xs text-muted-foreground py-1">Not enough data to generate a story yet.</p>
          )}

          {hasStory && (
            <>
              <div className="text-sm text-muted-foreground leading-relaxed">
                {story!.blocks.map((block, i) => {
                  if (block.type === "narrative" && block.text) {
                    return <span key={`n-${i}`}>{renderInlineCode(block.text)}</span>;
                  }
                  if (block.type === "beat" && block.text) {
                    return <BeatBlock key={`b-${i}`} kind={block.beatKind ?? "insight"} text={block.text} />;
                  }
                  if (block.type === "reference" && block.file) {
                    const idx = findFileIdx(diffs, block.file);
                    const diffFile = idx >= 0 ? diffs[idx] : null;

                    if (diffFile) {
                      return (
                        <InlineDiffBlock
                          key={`r-${i}`}
                          file={diffFile}
                          onNavigate={() => idx >= 0 && onSelectFile(idx)}
                          editCount={block.editCount}
                        />
                      );
                    }
                    // Fallback: filename link when no diff data found
                    const fileName = block.file.split("/").pop() ?? "file";
                    return (
                      <button
                        key={`r-${i}`}
                        type="button"
                        onClick={() => handleRefClick(block)}
                        className="inline text-primary hover:text-primary/80 font-mono text-[11px] underline underline-offset-2 decoration-primary/40 hover:decoration-primary transition-colors mx-0.5"
                        title={block.file}
                      >
                        {fileName}
                      </button>
                    );
                  }
                  return null;
                })}
              </div>
              <div className="flex items-center justify-between mt-2 pt-1.5 border-t border-border/30">
                {/* Verbosity toggle */}
                <div className="flex items-center gap-0.5 bg-muted/30 rounded p-0.5">
                  {(["summary", "standard", "detailed"] as const).map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleVerbosityChange(v); }}
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
                  onClick={(e) => {
                    e.stopPropagation();
                    setRegenerating(true);
                    fetchLevel(verbosity, true).finally(() => setRegenerating(false));
                  }}
                  className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground transition-colors"
                >
                  <RefreshCw size={10} className={cn(regenerating && "animate-spin")} />
                  {regenerating ? "Regenerating…" : "Regenerate"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
