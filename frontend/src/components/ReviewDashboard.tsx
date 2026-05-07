import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Plus, Minus, Pencil, ShieldCheck, ShieldAlert, Shield } from "lucide-react";
import { fetchStructuralDiff, type StructuralChange, type StructuralDiffResponse } from "../api/client";
import { Spinner } from "./ui/spinner";

// -- Category styling --

const CATEGORY_CONFIG: Record<string, { color: string; dot: string; label: string }> = {
  breaking: { color: "text-red-400", dot: "bg-red-400", label: "breaking" },
  body: { color: "text-yellow-400", dot: "bg-yellow-400", label: "body" },
  additive: { color: "text-green-400", dot: "bg-green-400", label: "additive" },
  "non-structural": { color: "text-zinc-400", dot: "bg-zinc-400", label: "non-structural" },
};

const CONFIDENCE_CONFIG: Record<string, { icon: typeof ShieldCheck; color: string; label: string }> = {
  HIGH: { icon: ShieldCheck, color: "text-green-400", label: "High Confidence" },
  MEDIUM: { icon: Shield, color: "text-yellow-400", label: "Medium Confidence" },
  LOW: { icon: ShieldAlert, color: "text-red-400", label: "Low Confidence" },
};

const KIND_ICONS: Record<string, typeof Plus> = {
  added: Plus,
  removed: Minus,
  modified: Pencil,
  moved: ArrowRightLeft,
};

// -- Triage Bar --

function TriageBar({ triage, activeFilter, onFilter }: {
  triage: Record<string, number>;
  activeFilter: string | null;
  onFilter: (cat: string | null) => void;
}) {
  const total = Object.values(triage).reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  return (
    <div className="flex items-center gap-0.5 h-7 rounded-md overflow-hidden border border-border">
      {(["breaking", "body", "additive", "non-structural"] as const).map((cat) => {
        const count = triage[cat] ?? 0;
        if (count === 0) return null;
        const pct = (count / total) * 100;
        const cfg = CATEGORY_CONFIG[cat]!;
        const isActive = activeFilter === cat;

        return (
          <button
            key={cat}
            onClick={() => onFilter(isActive ? null : cat)}
            className={`h-full flex items-center justify-center gap-1 px-2 text-[10px] font-medium transition-opacity ${cfg.color} ${isActive ? "opacity-100 bg-accent" : "opacity-70 hover:opacity-100"}`}
            style={{ width: `${Math.max(pct, 8)}%` }}
            title={`${count} ${cfg.label}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
            <span>{count}</span>
          </button>
        );
      })}
    </div>
  );
}

// -- Merge Confidence Badge --

function MergeConfidenceBadge({ confidence }: { confidence: string }) {
  const cfg = CONFIDENCE_CONFIG[confidence];
  if (!cfg) return null;
  const Icon = cfg.icon;

  return (
    <div className={`flex items-center gap-1.5 text-xs font-medium ${cfg.color}`}>
      <Icon size={14} />
      <span>{cfg.label}</span>
    </div>
  );
}

// -- Change Card --

function ChangeCard({ change }: { change: StructuralChange }) {
  const Icon = KIND_ICONS[change.kind] ?? Pencil;
  const catCfg = CATEGORY_CONFIG[change.category] ?? CATEGORY_CONFIG["non-structural"]!;
  const isHighRisk = change.risk > 0.7;

  return (
    <div className={`flex flex-col gap-1.5 px-3 py-2.5 rounded-md hover:bg-accent/50 transition-colors ${isHighRisk ? "border-l-2 border-red-400/60" : ""}`}>
      <div className="flex items-center gap-2">
        <Icon size={13} className={`shrink-0 ${catCfg.color}`} />
        <span className="text-xs font-mono text-muted-foreground truncate flex-1">{change.file}</span>
        <span className={`text-[10px] uppercase font-medium px-1.5 py-0.5 rounded ${catCfg.color} bg-accent/50`}>
          {change.category}
        </span>
        {isHighRisk && (
          <span className="text-[10px] font-bold text-red-400">⚠</span>
        )}
      </div>

      <div className="flex items-center gap-3 pl-5">
        {change.symbol && (
          <span className="text-xs font-semibold text-foreground">{change.symbol}</span>
        )}
        {change.refCount > 0 && (
          <span className="text-[10px] text-muted-foreground">
            {change.refCount} ref{change.refCount !== 1 ? "s" : ""}
          </span>
        )}
        {/* Ref tier chips */}
        {Object.entries(change.refTiers).map(([tier, count]) => (
          <span
            key={tier}
            className={`text-[10px] px-1 rounded ${tier === "unverified" ? "text-red-300 bg-red-400/10" : tier === "verified" ? "text-green-300 bg-green-400/10" : "text-blue-300 bg-blue-400/10"}`}
          >
            {count} {tier}
          </span>
        ))}
        <span className="text-[10px] text-muted-foreground ml-auto">
          risk {Math.round(change.risk * 100)}%
        </span>
      </div>

      {change.summary && (
        <p className="text-xs text-muted-foreground pl-5">{change.summary}</p>
      )}

      {change.testFiles.length > 0 && (
        <div className="flex items-center gap-1 pl-5">
          <span className="text-[10px] text-green-400">✓ tested</span>
          <span className="text-[10px] text-muted-foreground">({change.testFiles.length} file{change.testFiles.length !== 1 ? "s" : ""})</span>
        </div>
      )}
    </div>
  );
}

// -- Main Component --

export function ReviewDashboard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<StructuralDiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchStructuralDiff(jobId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? "Failed to load structural diff");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [jobId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
        <AlertTriangle size={16} className="text-yellow-400" />
        <span>{error}</span>
      </div>
    );
  }

  if (!data || !data.available) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        Structural analysis not available for this job.
      </div>
    );
  }

  if (data.changes.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        No structural changes detected.
      </div>
    );
  }

  // Sort by risk descending — highest risk first
  const sorted = [...data.changes].sort((a, b) => b.risk - a.risk);
  const filtered = categoryFilter
    ? sorted.filter((c) => c.category === categoryFilter)
    : sorted;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* Header: summary + merge confidence */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">Structural Review</h3>
          {data.mergeConfidence && <MergeConfidenceBadge confidence={data.mergeConfidence} />}
        </div>
        {data.summary && (
          <p className="text-xs text-muted-foreground mb-3">{data.summary}</p>
        )}
        {/* Triage bar (§9.2) */}
        <TriageBar triage={data.triage} activeFilter={categoryFilter} onFilter={setCategoryFilter} />
      </div>

      {/* Change list */}
      <div className="rounded-lg border border-border bg-card">
        <div className="px-3 py-2 border-b border-border flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">
            {filtered.length} change{filtered.length !== 1 ? "s" : ""}
            {categoryFilter && ` (${categoryFilter})`}
          </span>
          {categoryFilter && (
            <button
              onClick={() => setCategoryFilter(null)}
              className="text-[10px] text-primary hover:underline"
            >
              Show all
            </button>
          )}
        </div>
        <div className="divide-y divide-border">
          {filtered.map((change, i) => (
            <ChangeCard key={`${change.file}-${change.symbol}-${i}`} change={change} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default ReviewDashboard;
