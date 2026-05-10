import { Database } from "lucide-react";
import { Tooltip } from "../ui/tooltip";
import { type CacheEfficiencyResponse } from "../../api/client-analytics";

function formatPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function CacheEfficiencyChart({ data }: { data: CacheEfficiencyResponse }) {
  const { buckets, dimension } = data;
  if (!buckets.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Database size={14} />
          Cache Efficiency
        </div>
        <p className="text-muted-foreground text-sm mt-2">No cache data yet.</p>
      </div>
    );
  }

  // Overall hit rate
  const totalInput = buckets.reduce((s, b) => s + b.totalInputTokens, 0);
  const totalCacheRead = buckets.reduce((s, b) => s + b.totalCacheReadTokens, 0);
  const overallRate = totalInput > 0 ? totalCacheRead / totalInput : 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Database size={14} />
          Cache Efficiency
          <span className="text-[10px] font-normal normal-case">by {dimension}</span>
        </div>
        <div className="text-sm font-semibold text-foreground">{formatPct(overallRate)} overall</div>
      </div>

      <div className="space-y-2">
        {buckets.map((b) => {
          const barColor =
            b.cacheHitRate >= 0.6 ? "bg-green-500" : b.cacheHitRate >= 0.3 ? "bg-yellow-500" : "bg-red-500";
          return (
            <div key={b.bucket} className="space-y-0.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-foreground">{b.bucket}</span>
                <Tooltip
                  content={`${formatTokens(b.totalCacheReadTokens)} cache read / ${formatTokens(b.totalInputTokens)} total input · ${formatTokens(b.totalCacheWriteTokens)} written to cache`}
                >
                  <span className="cursor-help text-muted-foreground">
                    {formatPct(b.cacheHitRate)} · {b.jobCount} jobs
                  </span>
                </Tooltip>
              </div>
              <div className="h-1.5 rounded-full bg-border overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor}`}
                  style={{ width: `${Math.min(b.cacheHitRate * 100, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
