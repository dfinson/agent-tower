/**
 * CostDriversPanel — Per-job cost attribution breakdown.
 *
 * Shows cost by phase, tool category, and turn economics
 * with interactive charts. Appears in the job detail view
 * alongside MetricsPanel.
 */

import { useState, useEffect } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
} from "recharts";
import {
  TrendingUp,
  Layers,
  FileText,
  Zap,
} from "lucide-react";
import {
  fetchCostDrivers,
  fetchTurnEconomics,
  fetchFileAccess,
  type CostDriversResponse,
  type TurnEconomicsResponse,
  type FileAccessResponse,
} from "../api/client";
import { Spinner } from "./ui/spinner";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUsd(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

const PHASE_COLORS: Record<string, string> = {
  environment_setup: "#94a3b8",
  agent_reasoning: "#3b82f6",
  verification: "#f59e0b",
  finalization: "#10b981",
  unknown: "#6b7280",
};

const PIE_COLORS = [
  "#3b82f6", "#f59e0b", "#10b981", "#ef4444",
  "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface CostDriversPanelProps {
  jobId: string;
}

export default function CostDriversPanel({ jobId }: CostDriversPanelProps) {
  const [drivers, setDrivers] = useState<CostDriversResponse | null>(null);
  const [turns, setTurns] = useState<TurnEconomicsResponse | null>(null);
  const [fileAccess, setFileAccess] = useState<FileAccessResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchCostDrivers(jobId).catch(() => null),
      fetchTurnEconomics(jobId).catch(() => null),
      fetchFileAccess(jobId).catch(() => null),
    ]).then(([d, t, f]) => {
      if (cancelled) return;
      setDrivers(d);
      setTurns(t);
      setFileAccess(f);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [jobId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spinner className="mr-2" /> Loading cost analytics…
      </div>
    );
  }

  const phaseBuckets = drivers?.dimensions?.phase ?? [];
  const categoryBuckets = drivers?.dimensions?.tool_category ?? [];
  const turnCurve = turns?.turnCurve ?? [];
  const hasData = phaseBuckets.length > 0 || turns?.totalTurns;

  if (!hasData) {
    return (
      <div className="text-muted-foreground text-center py-8">
        No cost attribution data available for this job.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Turn Economics Summary */}
      {turns && turns.totalTurns > 0 && (
        <section>
          <h3 className="text-sm font-medium text-foreground flex items-center gap-1.5 mb-3">
            <TrendingUp className="h-4 w-4" /> Turn Economics
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Total Turns" value={String(turns.totalTurns)} />
            <StatCard label="Avg Cost/Turn" value={formatUsd(turns.avgTurnCostUsd)} />
            <StatCard label="Peak Turn" value={formatUsd(turns.peakTurnCostUsd)} />
            <StatCard
              label="Cost Ratio (1st/2nd Half)"
              value={
                turns.costSecondHalfUsd > 0
                  ? `${(turns.costFirstHalfUsd / turns.costSecondHalfUsd).toFixed(2)}x`
                  : "—"
              }
            />
          </div>
          {/* Turn cost curve */}
          {turnCurve.length > 1 && (
            <div className="mt-3 h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={turnCurve.map((t) => ({
                    turn: t.bucket,
                    cost: t.cost_usd,
                    tokens: t.input_tokens + t.output_tokens,
                  }))}
                >
                  <XAxis dataKey="turn" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => formatUsd(v)} />
                  <RechartsTooltip
                    formatter={(v: unknown, name: unknown) =>
                      name === "cost" ? formatUsd(Number(v ?? 0)) : formatTokens(Number(v ?? 0))
                    }
                  />
                  <Area
                    type="monotone"
                    dataKey="cost"
                    stroke="#3b82f6"
                    fill="#3b82f6"
                    fillOpacity={0.15}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>
      )}

      {/* Cost by Phase */}
      {phaseBuckets.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-foreground flex items-center gap-1.5 mb-3">
            <Layers className="h-4 w-4" /> Cost by Phase
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={phaseBuckets.map((b) => ({
                      name: b.bucket,
                      value: b.cost_usd,
                    }))}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={70}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`
                    }
                    labelLine={false}
                  >
                    {phaseBuckets.map((b, i) => (
                      <Cell
                        key={b.bucket}
                        fill={PHASE_COLORS[b.bucket] ?? PIE_COLORS[i % PIE_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <RechartsTooltip formatter={(v: unknown) => formatUsd(Number(v ?? 0))} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="text-xs space-y-1.5">
              {phaseBuckets
                .sort((a, b) => b.cost_usd - a.cost_usd)
                .map((b) => (
                  <div key={b.bucket} className="flex justify-between items-center">
                    <span className="flex items-center gap-1.5">
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{
                          backgroundColor:
                            PHASE_COLORS[b.bucket] ?? "#6b7280",
                        }}
                      />
                      {b.bucket.replace(/_/g, " ")}
                    </span>
                    <span className="font-mono">{formatUsd(b.cost_usd)}</span>
                  </div>
                ))}
            </div>
          </div>
        </section>
      )}

      {/* Cost by Tool Category */}
      {categoryBuckets.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-foreground flex items-center gap-1.5 mb-3">
            <Zap className="h-4 w-4" /> Cost by Tool Category
          </h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={categoryBuckets
                  .sort((a, b) => b.call_count - a.call_count)
                  .map((b) => ({
                    name: b.bucket,
                    calls: b.call_count,
                    inputTokens: b.input_tokens,
                    outputTokens: b.output_tokens,
                  }))}
                layout="vertical"
              >
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis dataKey="name" type="category" width={80} tick={{ fontSize: 11 }} />
                <RechartsTooltip />
                <Bar dataKey="calls" fill="#3b82f6" name="Calls" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* File Access Stats */}
      {fileAccess && fileAccess.stats.total_accesses > 0 && (
        <section>
          <h3 className="text-sm font-medium text-foreground flex items-center gap-1.5 mb-3">
            <FileText className="h-4 w-4" /> File I/O
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <StatCard label="Total Reads" value={String(fileAccess.stats.total_reads)} />
            <StatCard label="Total Writes" value={String(fileAccess.stats.total_writes)} />
            <StatCard label="Unique Files" value={String(fileAccess.stats.unique_files)} />
            <StatCard
              label="Rereads"
              value={String(fileAccess.stats.reread_count)}
              warn={fileAccess.stats.reread_count > fileAccess.stats.unique_files}
            />
          </div>
          {fileAccess.topFiles.length > 0 && (
            <div className="text-xs space-y-1">
              <div className="text-muted-foreground font-medium">Most Accessed Files</div>
              {fileAccess.topFiles.slice(0, 8).map((f) => (
                <div key={f.file_path} className="flex justify-between items-center font-mono">
                  <span className="truncate max-w-[70%]">{f.file_path}</span>
                  <span className="text-muted-foreground">
                    {f.read_count}R / {f.write_count}W
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-border bg-card px-3 py-2",
        warn && "border-yellow-500/50",
      )}
    >
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("text-sm font-mono font-medium", warn && "text-yellow-500")}>
        {value}
      </div>
    </div>
  );
}
