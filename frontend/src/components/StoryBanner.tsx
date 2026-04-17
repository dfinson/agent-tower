/**
 * StoryBanner — collapsible code-review narrative embedded in the DiffViewer.
 *
 * Renders the LLM-generated story with change references as small inline
 * filename links. Clicking a link selects that file in the diff sidebar.
 */

import { useEffect, useState, useCallback, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BookOpen, ChevronDown, RefreshCw } from "lucide-react";
import { fetchJobStory } from "../api/client";
import type { StoryBlock, StoryResponse } from "../api/types";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";

export interface StoryRefHandler {
  /** Called when the user clicks an inline file reference. */
  onRefClick: (file: string, turnId?: string) => void;
}

interface StoryBannerProps {
  jobId: string;
  handlers: StoryRefHandler;
}

// ---------------------------------------------------------------------------
// Inline reference link
// ---------------------------------------------------------------------------

function RefLink({
  block,
  onClick,
}: {
  block: StoryBlock;
  onClick: () => void;
}) {
  const fileName = block.file?.split("/").pop() ?? block.file ?? "file";
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-0.5 text-primary hover:text-primary/80 font-mono text-[11px] underline underline-offset-2 decoration-primary/40 hover:decoration-primary transition-colors mx-0.5"
      title={block.file ?? undefined}
    >
      {fileName}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Banner
// ---------------------------------------------------------------------------

export function StoryBanner({ jobId, handlers }: StoryBannerProps) {
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(
    async (regen = false) => {
      try {
        if (regen) setRegenerating(true);
        else setLoading(true);
        const data = await fetchJobStory(jobId, regen);
        setStory(data);
        setLoaded(true);
      } catch {
        // silently degrade — story is optional
        setLoaded(true);
      } finally {
        setLoading(false);
        setRegenerating(false);
      }
    },
    [jobId],
  );

  // Lazy load: only fetch when first expanded
  useEffect(() => {
    if (open && !loaded) load();
  }, [open, loaded, load]);

  const hasStory = story && story.blocks.length > 0;

  // Build renderable content: interleave narrative spans and inline ref links
  const renderBlocks = useCallback((): ReactNode[] => {
    if (!story) return [];
    const nodes: ReactNode[] = [];
    for (const [i, block] of story.blocks.entries()) {
      if (block.type === "narrative" && block.text) {
        nodes.push(
          <ReactMarkdown
            key={`n-${i}`}
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <span className="[&:not(:first-child)]:mt-1.5 block">{children}</span>,
              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
              em: ({ children }) => <em>{children}</em>,
              h1: ({ children }) => <span className="block font-semibold text-foreground mt-3 mb-1">{children}</span>,
              h2: ({ children }) => <span className="block font-semibold text-foreground mt-3 mb-1">{children}</span>,
              h3: ({ children }) => <span className="block font-semibold text-foreground mt-2 mb-1">{children}</span>,
              code: ({ children }) => <code className="text-[11px] bg-muted/60 rounded px-1 py-0.5 font-mono">{children}</code>,
            }}
          >
            {block.text}
          </ReactMarkdown>,
        );
      } else if (block.type === "reference") {
        nodes.push(
          <RefLink
            key={`r-${i}`}
            block={block}
            onClick={() => handlers.onRefClick(block.file ?? "", block.turnId ?? undefined)}
          />,
        );
      }
    }
    return nodes;
  }, [story, handlers]);

  return (
    <div className="rounded-lg border border-border/60 bg-card">
      {/* Toggle header */}
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

      {/* Expandable content */}
      {open && (
        <div className="border-t border-border/40 px-3 py-2.5">
          {loading && (
            <div className="flex items-center gap-2 py-2 text-muted-foreground">
              <Spinner />
              <span className="text-xs">Generating story…</span>
            </div>
          )}

          {loaded && !hasStory && !loading && (
            <p className="text-xs text-muted-foreground py-1">Not enough data to generate a story yet.</p>
          )}

          {hasStory && (
            <>
              <div className="text-sm text-muted-foreground leading-relaxed space-y-0.5">
                {renderBlocks()}
              </div>
              <div className="flex justify-end mt-2 pt-1.5 border-t border-border/30">
                <button
                  type="button"
                  disabled={regenerating}
                  onClick={(e) => {
                    e.stopPropagation();
                    load(true);
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
