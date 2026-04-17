/**
 * StoryPanel — structured code-review narrative.
 *
 * Renders alternating narrative (markdown) and reference (clickable change
 * cards) blocks. References are validated against real telemetry spans — they
 * always point to actual changes.
 */

import { useEffect, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileCode2, RefreshCw, BookOpen } from "lucide-react";
import { fetchJobStory } from "../api/client";
import type { StoryBlock, StoryResponse } from "../api/types";
import { Button } from "./ui/button";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";

interface StoryPanelProps {
  jobId: string;
  /** Navigate the diff viewer to a specific step. */
  onNavigateToStep?: (stepNumber: number) => void;
}

// ---------------------------------------------------------------------------
// Reference card
// ---------------------------------------------------------------------------

function ReferenceCard({
  block,
  index,
  onNavigate,
}: {
  block: StoryBlock;
  index: number;
  onNavigate?: (stepNumber: number) => void;
}) {
  const fileName = block.file?.split("/").pop() ?? block.file ?? "unknown";
  const dirPath = block.file?.includes("/")
    ? block.file.slice(0, block.file.lastIndexOf("/"))
    : "";

  return (
    <button
      type="button"
      onClick={() => block.stepNumber != null && onNavigate?.(block.stepNumber)}
      className={cn(
        "group w-full text-left rounded-lg border border-border/60 bg-card/50",
        "px-4 py-3 my-2 transition-colors",
        "hover:border-primary/40 hover:bg-primary/5",
        block.stepNumber != null && onNavigate && "cursor-pointer",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 mt-0.5 rounded-md bg-primary/10 p-1.5 text-primary">
          <FileCode2 size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-xs font-mono text-muted-foreground">
              #{index + 1}
            </span>
            <span className="font-medium text-sm truncate">{fileName}</span>
            {dirPath && (
              <span className="text-xs text-muted-foreground truncate">
                {dirPath}/
              </span>
            )}
          </div>
          {block.stepTitle && (
            <p className="text-xs text-muted-foreground mt-0.5">
              Step {block.stepNumber}: {block.stepTitle}
            </p>
          )}
          {block.why && (
            <p className="text-sm text-foreground/80 mt-1 leading-snug">
              {block.why}
            </p>
          )}
          {block.editCount != null && block.editCount > 1 && (
            <span className="inline-block mt-1 text-[10px] bg-muted text-muted-foreground rounded-full px-2 py-0.5">
              {block.editCount} edits
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function StoryPanel({ jobId, onNavigateToStep }: StoryPanelProps) {
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (regen = false) => {
      try {
        if (regen) setRegenerating(true);
        else setLoading(true);
        setError(null);
        const data = await fetchJobStory(jobId, regen);
        setStory(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load story");
      } finally {
        setLoading(false);
        setRegenerating(false);
      }
    },
    [jobId],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Track reference index across all blocks for numbering
  let refIndex = 0;

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <Spinner />
        <p className="text-sm">Generating story…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <p className="text-sm">{error}</p>
        <Button variant="outline" size="sm" onClick={() => load()}>
          Retry
        </Button>
      </div>
    );
  }

  if (!story || story.blocks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <BookOpen size={32} className="opacity-50" />
        <p className="text-sm">Not enough data to generate a story yet.</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 space-y-1">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-1.5">
          <BookOpen size={14} />
          Code Review Story
        </h3>
        <Button
          variant="ghost"
          size="sm"
          disabled={regenerating}
          onClick={() => load(true)}
          className="text-xs gap-1"
        >
          <RefreshCw size={12} className={cn(regenerating && "animate-spin")} />
          {regenerating ? "Regenerating…" : "Regenerate"}
        </Button>
      </div>

      {/* Blocks */}
      {story.blocks.map((block, i) => {
        if (block.type === "narrative" && block.text) {
          return (
            <div
              key={i}
              className="prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-4 prose-headings:mb-2"
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {block.text}
              </ReactMarkdown>
            </div>
          );
        }
        if (block.type === "reference") {
          const idx = refIndex++;
          return (
            <ReferenceCard
              key={i}
              block={block}
              index={idx}
              onNavigate={onNavigateToStep}
            />
          );
        }
        return null;
      })}
    </div>
  );
}
