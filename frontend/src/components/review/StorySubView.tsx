/**
 * Story sub-view — trail-based narrative code review story.
 *
 * Stories are pre-generated in the background at all verbosity levels.
 * This component polls until the story is ready, then renders it.
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import { AlertTriangle, BookOpen, RefreshCw } from "lucide-react";
import { fetchJobStory } from "../../api/client";
import { useStore } from "../../store";
import { selectJobStory } from "../../store/selectors";
import type { StoryBlock } from "../../api/types";
import { Spinner } from "../ui/spinner";
import { cn } from "../../lib/utils";

interface StorySubViewProps {
  jobId: string;
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

  // Track which verbosity levels are pending (generating in background)
  const [pending, setPending] = useState<Record<Verbosity, boolean>>({
    summary: false, standard: false, detailed: false,
  });
  const pollTimers = useRef<Record<Verbosity, ReturnType<typeof setTimeout> | null>>({
    summary: null, standard: null, detailed: null,
  });

  const fetchLevel = useCallback(
    async (v: Verbosity, regen = false) => {
      setFetching((prev) => ({ ...prev, [v]: true }));
      try {
        const res = await fetchJobStory(jobId, regen, v);
        if (res.blocks && res.blocks.length > 0) {
          setStory(jobId, res);
          setPending((prev) => ({ ...prev, [v]: false }));
        } else if (res.pending) {
          // Story is being generated — poll again shortly
          setPending((prev) => ({ ...prev, [v]: true }));
          if (pollTimers.current[v]) clearTimeout(pollTimers.current[v]!);
          pollTimers.current[v] = setTimeout(() => fetchLevel(v), 4000);
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

  // Cleanup poll timers on unmount
  useEffect(() => {
    return () => {
      Object.values(pollTimers.current).forEach((t) => t && clearTimeout(t));
    };
  }, []);

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
  const loading = (fetching[verbosity] || pending[verbosity]) && !story;
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
        <div className="flex flex-col items-center justify-center h-48 gap-2">
          <Spinner size="md" />
          {pending[verbosity] && (
            <span className="text-xs text-muted-foreground">Generating story\u2026</span>
          )}
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

export function StorySubView({ jobId }: StorySubViewProps) {
  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto w-full flex flex-col gap-4">
        <TrailStoryFallback jobId={jobId} />
      </div>
    </div>
  );
}
