/**
 * ReviewDashboard — orchestrator for the Review tab.
 *
 * Sub-views:
 * - Dashboard: structural triage, change cards, merge confidence
 * - Timeline: per-session structural changes (hidden for single-session jobs)
 * - Story: structured review story with verdict
 *
 * Degradation: when CodeRecon is unavailable (available=false on structural-diff),
 * the Story sub-view becomes default. Dashboard shows info banner. Timeline hidden.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Plus, Minus, Pencil, ShieldCheck, ShieldAlert, Shield, Info } from "lucide-react";
import { fetchStructuralDiff, fetchMultiSession, type StructuralChange, type StructuralDiffResponse } from "../api/client";
import { Spinner } from "./ui/spinner";
import { ReviewSubTabs, type ReviewSubView } from "./review/ReviewSubTabs";
import { TimelineSubView } from "./review/TimelineSubView";
import { StorySubView } from "./review/StorySubView";
import { ImpactGraphModal } from "./review/ImpactGraphModal";

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
        const cfg = CATEGORY_CONFIG[cat]!;
        const pct = (count / total) * 100;
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

function ChangeCard({ change, onClick }: { change: StructuralChange; onClick: () => void }) {
  const Icon = KIND_ICONS[change.kind] ?? Pencil;
  const catCfg = CATEGORY_CONFIG[change.category] ?? CATEGORY_CONFIG["non-structural"]!;
  const isHighRisk = change.risk > 0.7;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left flex flex-col gap-1.5 px-3 py-2.5 rounded-md hover:bg-accent/50 transition-colors cursor-pointer ${isHighRisk ? "border-l-2 border-red-400/60" : ""}`}
    >
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
    </button>
  );
}

// -- Dashboard Sub-View (structural analysis available) --

function DashboardSubView({ data, onSymbolClick }: { data: StructuralDiffResponse; onSymbolClick: (symbol: string) => void }) {
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  if (data.changes.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        No structural changes detected.
      </div>
    );
  }

  const sorted = [...data.changes].sort((a, b) => b.risk - a.risk);
  const filtered = categoryFilter
    ? sorted.filter((c) => c.category === categoryFilter)
    : sorted;

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* Header */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">Structural Review</h3>
          {data.mergeConfidence && <MergeConfidenceBadge confidence={data.mergeConfidence} />}
        </div>
        {data.summary && (
          <p className="text-xs text-muted-foreground mb-3">{data.summary}</p>
        )}
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
            <ChangeCard
              key={`${change.file}-${change.symbol}-${i}`}
              change={change}
              onClick={() => change.symbol && onSymbolClick(change.symbol)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// -- Degraded Dashboard --

function DegradedDashboard() {
  return (
    <div className="flex flex-col items-center justify-center h-48 gap-3">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Info size={16} className="text-blue-400" />
        <span>Structural analysis unavailable — showing trail-based review</span>
      </div>
      <p className="text-xs text-muted-foreground max-w-md text-center">
        The structural index is not available for this job&apos;s repository.
        The Story view provides a trail-based review of the agent&apos;s work.
      </p>
    </div>
  );
}

// -- Main Component --

export function ReviewDashboard({ jobId }: { jobId: string }) {
  const [structData, setStructData] = useState<StructuralDiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMultiSession, setHasMultiSession] = useState(false);

  // Sub-view state — default depends on availability
  const [subView, setSubView] = useState<ReviewSubView>("dashboard");

  // Impact graph modal state
  const [impactSymbol, setImpactSymbol] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    // Fetch structural diff + probe multi-session in parallel
    Promise.all([
      fetchStructuralDiff(jobId),
      fetchMultiSession(jobId).catch(() => null),
    ]).then(([diff, multi]) => {
      if (cancelled) return;
      setStructData(diff);
      setHasMultiSession(multi != null && multi.available && multi.sessions.length > 1);

      // If structural analysis unavailable, default to story view
      if (!diff.available) {
        setSubView("story");
      }
    }).catch((err) => {
      if (!cancelled) setError(err?.message ?? "Failed to load review data");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, [jobId]);

  const handleSymbolClick = useCallback((symbol: string) => {
    setImpactSymbol(symbol);
  }, []);

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

  const available = structData?.available ?? false;
  // In degraded mode: hide timeline, dashboard shows info banner
  const showTimeline = available && hasMultiSession;

  return (
    <div className="flex flex-col h-full">
      {/* Sub-view tabs */}
      <ReviewSubTabs
        active={subView}
        onChange={setSubView}
        showTimeline={showTimeline}
      />

      {/* Sub-view content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {subView === "dashboard" && (
          available && structData
            ? <DashboardSubView data={structData} onSymbolClick={handleSymbolClick} />
            : <DegradedDashboard />
        )}
        {subView === "timeline" && showTimeline && (
          <TimelineSubView jobId={jobId} />
        )}
        {subView === "story" && (
          <StorySubView jobId={jobId} />
        )}
      </div>

      {/* Impact graph modal */}
      {impactSymbol && (
        <ImpactGraphModal
          jobId={jobId}
          symbol={impactSymbol}
          onClose={() => setImpactSymbol(null)}
        />
      )}
    </div>
  );
}

export default ReviewDashboard;
