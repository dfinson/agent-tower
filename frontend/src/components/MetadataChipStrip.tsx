import { ExternalLink, AlertTriangle, ArrowDownCircle, Loader2, Coins } from "lucide-react";
import type { JobSummary } from "../store";
import { cn } from "../lib/utils";

interface MetadataChipStripProps {
  job: JobSummary;
  hasMergeConflict: boolean;
  className?: string;
}

function Chip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-muted text-muted-foreground whitespace-nowrap", className)}>
      {children}
    </span>
  );
}

export function MetadataChipStrip({ job, hasMergeConflict, className }: MetadataChipStripProps) {
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
        <Chip className="bg-emerald-500/15 text-emerald-400">
          <Coins size={10} />
          {formatCostChip(job.totalCostUsd, job.totalTokens)}
        </Chip>
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
  const cost = costUsd < 0.01
    ? `$${costUsd.toFixed(4)}`
    : costUsd < 1
      ? `$${costUsd.toFixed(2)}`
      : `$${costUsd.toFixed(2)}`;
  if (tokens == null || tokens === 0) return cost;
  const tok = tokens >= 1_000_000
    ? `${(tokens / 1_000_000).toFixed(1)}M`
    : tokens >= 1_000
      ? `${(tokens / 1_000).toFixed(0)}k`
      : `${tokens}`;
  return `${cost} · ${tok} tok`;
}
