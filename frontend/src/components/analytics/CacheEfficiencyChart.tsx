import { Database } from "lucide-react";
import { Tooltip } from "../ui/tooltip";
import { type CacheEfficiencyResponse } from "../../api/client-analytics";
import { fetchCacheEfficiency } from "../../api/client-analytics";
import { useState } from "react";

function formatPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function CacheEfficiencyChart({ data: initialData, period }: { data: CacheEfficiencyResponse; period?: number }) {
  const [data, setData] = useState(initialData);
  const [activeDimension, setActiveDimension] = useState(data.dimension);
  const [loading, setLoading] = useState(false);

  const switchDimension = (dim: string) => {
    if (dim === activeDimension) return;
    setLoading(true);
    setActiveDimension(dim);
    fetchCacheEfficiency(period ?? 30, dim)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  const { buckets } = data;
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
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-border overflow-hidden text-[11px]">
            {["phase", "activity"].map((dim) => (
              <button
                key={dim}
                onClick={() => switchDimension(dim)}
                disabled={loading}
                className={`px-2 py-0.5 capitalize transition-colors ${
                  activeDimension === dim
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent/50"
                }`}
              >
                By {dim}
              </button>
            ))}
          </div>
          <div className="text-sm font-semibold text-foreground">{formatPct(overallRate)} overall</div>
        </div>
      </div>

      <div className="space-y-2">
        {buckets.map((b) => {
          const barColor =
            b.cacheHitRate >= 0.7 ? "bg-green-500" : b.cacheHitRate >= 0.4 ? "bg-yellow-500" : "bg-red-500";
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
