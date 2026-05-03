import { useState, useRef, useEffect, useCallback } from "react";
import { ExternalLink, AlertTriangle, ArrowDownCircle, Loader2, Coins } from "lucide-react";
import type { JobSummary } from "../store";
import { cn } from "../lib/utils";

interface MetadataChipStripProps {
  job: JobSummary;
  hasMergeConflict: boolean;
  className?: string;
  onCostClick?: () => void;
}

function Chip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-muted text-muted-foreground whitespace-nowrap", className)}>
      {children}
    </span>
  );
}

function CostChip({ job, onCostClick }: { job: JobSummary; onCostClick?: () => void }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const chipRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => setShowTooltip(false), []);

  useEffect(() => {
    if (!showTooltip) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      if (
        chipRef.current?.contains(e.target as Node) ||
        tooltipRef.current?.contains(e.target as Node)
      ) return;
      close();
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
    };
  }, [showTooltip, close]);

  const costUsd = job.totalCostUsd!;
  const label = formatCostChip(costUsd, job.totalTokens);

  return (
    <span className="relative">
      <button
        ref={chipRef}
        type="button"
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
          "bg-emerald-500/15 text-emerald-400",
          onCostClick && "cursor-pointer hover:bg-emerald-500/25 transition-colors",
        )}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={onCostClick}
        aria-label="View cost breakdown"
      >
        <Coins size={10} />
        {label}
      </button>
      {showTooltip && (
        <div
          ref={tooltipRef}
          role="tooltip"
          className="absolute z-50 top-full mt-1 left-0 w-52 rounded-lg border border-border bg-popover p-2.5 shadow-lg text-[11px] text-popover-foreground"
        >
          <div className="space-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">API cost</span>
              <span className="font-medium">{formatUsd(costUsd)}</span>
            </div>
            {job.inputTokens != null && job.inputTokens > 0 && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Input tokens</span>
                <span>{formatTokens(job.inputTokens)}</span>
              </div>
            )}
            {job.outputTokens != null && job.outputTokens > 0 && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Output tokens</span>
                <span>{formatTokens(job.outputTokens)}</span>
              </div>
            )}
            {job.totalTokens != null && job.totalTokens > 0 && (
              <div className="flex justify-between border-t border-border pt-1 mt-1">
                <span className="text-muted-foreground">Total tokens</span>
                <span className="font-medium">{formatTokens(job.totalTokens)}</span>
              </div>
            )}
          </div>
          <p className="mt-2 text-[10px] text-muted-foreground/70 leading-tight">
            Raw API cost — may not reflect your actual bill (cached tokens, batching, and provider discounts apply).
          </p>
          {onCostClick && (
            <p className="mt-1 text-[10px] text-primary/70">Click for full breakdown →</p>
          )}
        </div>
      )}
    </span>
  );
}

export function MetadataChipStrip({ job, hasMergeConflict, className, onCostClick }: MetadataChipStripProps) {
  const isPreparing = job.state === "preparing";

  return (
    <div className={cn("flex items-center gap-1.5 overflow-x-auto scrollbar-none", className)}>
      {job.branch && (
        <Chip>{job.branch} → {job.baseRef}</Chip>
      )}
      {job.model && <Chip>{job.model}</Chip>}
      <Chip>{timeAgo(job.createdAt)}</Chip>
      {job.prUrl && (
        <a href={job.prUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-muted text-primary hover:underline whitespace-nowrap">
          <ExternalLink size={10} /> PR
        </a>
      )}
      {/* Cost / token chip */}
      {(job.totalCostUsd != null && job.totalCostUsd > 0) && (
        <CostChip job={job} onCostClick={onCostClick} />
      )}
      {/* Status chips */}
      {job.modelDowngraded && (
        <Chip className="bg-amber-500/15 text-amber-500">
          <ArrowDownCircle size={10} /> Downgraded
        </Chip>
      )}
      {hasMergeConflict && (
        <Chip className="bg-amber-500/15 text-amber-500">
          <AlertTriangle size={10} /> Conflict
        </Chip>
      )}
      {job.state === "failed" && (
        <Chip className="bg-red-500/15 text-red-500">
          Failed{job.failureReason ? `: ${job.failureReason.slice(0, 40)}` : ""}
        </Chip>
      )}
      {isPreparing && (
        <Chip className="bg-violet-500/15 text-violet-400">
          <Loader2 size={10} className="animate-spin" />
          {job.setupStep === "creating_workspace" ? "Creating workspace…" : "Setting up…"}
        </Chip>
      )}
    </div>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatCostChip(costUsd: number, tokens?: number | null): string {
  const cost = formatUsd(costUsd);
  if (tokens == null || tokens === 0) return cost;
  return `${cost} · ${formatTokensCompact(tokens)} tok`;
}

function formatUsd(costUsd: number): string {
  if (costUsd < 0.01) return `$${costUsd.toFixed(4)}`;
  return `$${costUsd.toFixed(2)}`;
}

function formatTokensCompact(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}k`;
  return `${tokens}`;
}

function formatTokens(tokens: number): string {
  return tokens.toLocaleString();
}
