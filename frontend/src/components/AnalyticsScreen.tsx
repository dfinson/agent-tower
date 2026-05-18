import { useState, useEffect, useRef, useCallback } from "react";
import {
  BarChart3, DollarSign, Clock, Wrench, GitBranch, Zap, Loader2, Download,
} from "lucide-react";
import {
  fetchScorecard,
  fetchModelComparison,
  fetchAnalyticsTools,
  fetchAnalyticsRepos,
  fetchFleetCostDrivers,
  fetchFleetLatencyDrivers,
  fetchObservations,
  dismissObservation,
  fetchYield,
  fetchCacheEfficiency,
  fetchModelEfficiency,

  fetchExecutiveSummary,
  exportCostDrivers,
  type ScorecardResponse,
  type ModelComparisonResponse,
  type AnalyticsTools,
  type AnalyticsRepos,
  type FleetCostDriversResponse,
  type FleetLatencyDriversResponse,
  type Observation,
  type YieldResponse,
  type CacheEfficiencyResponse,
  type ModelEfficiencyResponse,

  type ExecutiveSummaryResponse,
} from "../api/client";
import {
  formatRelativeTime,
  CollapsibleSection,
  SectionSkeleton,
  BudgetCard,
  ActivityCard,
  CostTrendChart,
  ModelComparison,
  ObservationsPanel,
  RepoBreakdown,
  ToolHealth,
  FleetCostDriverInsights,
  FleetLatencyDriverInsights,
  YieldCard,
  CacheEfficiencyChart,
  ModelCostCard,
} from "./AnalyticsWidgets";
import { RecentJobsPreview } from "./analytics/RecentJobsPreview";

import { ExecutiveSummary } from "./analytics/ExecutiveSummary";
import { MetricsChatPanel } from "./metrics/MetricsChatPanel";
import { PinnedMetricsGrid } from "./metrics/PinnedMetricsGrid";

function ExportDropdown({ period }: { period: number }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent/50 transition-colors"
      >
        <Download size={14} />
        Export
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-32 rounded-md border border-border bg-card shadow-lg z-10">
          <a
            href={exportCostDrivers(period, "csv")}
            download
            className="block px-3 py-2 text-sm text-foreground hover:bg-accent/50 transition-colors"
            onClick={() => setOpen(false)}
          >
            CSV
          </a>
          <a
            href={exportCostDrivers(period, "json")}
            download
            className="block px-3 py-2 text-sm text-foreground hover:bg-accent/50 transition-colors"
            onClick={() => setOpen(false)}
          >
            JSON
          </a>
        </div>
      )}
    </div>
  );
}

export function AnalyticsScreen() {
  const [period, setPeriod] = useState(7);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [pinnedRefreshKey, setPinnedRefreshKey] = useState(0);
  const handleMetricPinned = useCallback(() => setPinnedRefreshKey((k) => k + 1), []);
  const [scorecard, setScorecard] = useState<ScorecardResponse | null>(null);
  const [modelComparison, setModelComparison] = useState<ModelComparisonResponse | null>(null);
  const [tools, setTools] = useState<AnalyticsTools | null>(null);
  const [repos, setRepos] = useState<AnalyticsRepos | null>(null);
  const [fleetDrivers, setFleetDrivers] = useState<FleetCostDriversResponse | null>(null);
  const [fleetLatency, setFleetLatency] = useState<FleetLatencyDriversResponse | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [yieldData, setYieldData] = useState<YieldResponse | null>(null);
  const [cacheEfficiency, setCacheEfficiency] = useState<CacheEfficiencyResponse | null>(null);
  const [modelEfficiency, setModelEfficiency] = useState<ModelEfficiencyResponse | null>(null);


  const [executiveSummary, setExecutiveSummary] = useState<ExecutiveSummaryResponse | null>(null);

  // Per-section loading states
  const [scorecardLoading, setScorecardLoading] = useState(true);
  const [modelLoading, setModelLoading] = useState(true);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [reposLoading, setReposLoading] = useState(true);
  const [driversLoading, setDriversLoading] = useState(true);
  const [latencyLoading, setLatencyLoading] = useState(true);
  const [obsLoading, setObsLoading] = useState(true);
  const [yieldLoading, setYieldLoading] = useState(true);
  const [cacheLoading, setCacheLoading] = useState(true);

  const [scorecardError, setScorecardError] = useState<string | null>(null);

  // Timestamp of last successful data load
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Refresh counter — incrementing triggers the effect to re-fetch
  const [refreshCounter, setRefreshCounter] = useState(0);
  const loadData = useCallback(() => {
    setRefreshing(true);
    setRefreshCounter((c) => c + 1);
  }, []);

  // Abort controller to cancel in-flight requests when filters change
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Cancel any previous in-flight requests
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    const isAborted = () => signal.aborted;
    const swallow = (err: unknown) => {
      if (err instanceof DOMException && err.name === "AbortError") return;
      throw err;
    };

    setScorecardLoading(true);
    setModelLoading(true);
    setToolsLoading(true);
    setReposLoading(true);
    setDriversLoading(true);
    setLatencyLoading(true);
    setObsLoading(true);
    setYieldLoading(true);
    setCacheLoading(true);
    setScorecardError(null);

    // Fire all fetches independently — use actual period (no forced 30-day min)
    fetchScorecard(period)
      .then((sc) => { if (!isAborted()) { setScorecard(sc); setLastUpdated(new Date()); } })
      .catch((err) => { if (!isAborted()) setScorecardError(err.message || "Failed to load scorecard"); })
      .catch(swallow)
      .finally(() => { if (!isAborted()) { setScorecardLoading(false); setRefreshing(false); } });

    fetchModelComparison(period, selectedRepo || undefined)
      .then((d) => { if (!isAborted()) setModelComparison(d); })
      .catch(swallow)
      .finally(() => { if (!isAborted()) setModelLoading(false); });

    fetchAnalyticsTools(period)
      .then((d) => { if (!isAborted()) setTools(d); })
      .catch(swallow)
      .finally(() => { if (!isAborted()) setToolsLoading(false); });

    fetchAnalyticsRepos(period)
      .then((d) => { if (!isAborted()) setRepos(d); })
      .catch(swallow)
      .finally(() => { if (!isAborted()) setReposLoading(false); });

    fetchFleetCostDrivers(period)
      .then((d) => { if (!isAborted()) setFleetDrivers(d); })
      .catch((err) => { swallow(err); if (!isAborted()) setFleetDrivers(null); })
      .finally(() => { if (!isAborted()) setDriversLoading(false); });

    fetchFleetLatencyDrivers(period)
      .then((d) => { if (!isAborted()) setFleetLatency(d); })
      .catch((err) => { swallow(err); if (!isAborted()) setFleetLatency(null); })
      .finally(() => { if (!isAborted()) setLatencyLoading(false); });

    fetchObservations()
      .then((obs) => { if (!isAborted()) setObservations(obs?.observations ?? []); })
      .catch(swallow)
      .finally(() => { if (!isAborted()) setObsLoading(false); });

    fetchYield(period)
      .then((d) => { if (!isAborted()) setYieldData(d); })
      .catch((err) => { swallow(err); if (!isAborted()) setYieldData(null); })
      .finally(() => { if (!isAborted()) setYieldLoading(false); });

    fetchCacheEfficiency(period)
      .then((d) => { if (!isAborted()) setCacheEfficiency(d); })
      .catch((err) => { swallow(err); if (!isAborted()) setCacheEfficiency(null); })
      .finally(() => { if (!isAborted()) setCacheLoading(false); });

    fetchModelEfficiency(period)
      .then((d) => { if (!isAborted()) setModelEfficiency(d); })
      .catch(swallow);

    fetchExecutiveSummary(period)
      .then((d) => { if (!isAborted()) setExecutiveSummary(d); })
      .catch(swallow);

    return () => { controller.abort(); };
  }, [period, selectedRepo, refreshCounter]);

  const handleDismissObservation = async (id: number) => {
    try {
      await dismissObservation(id);
      setObservations((prev) => prev.filter((o) => o.id !== id));
    } catch { /* ignore */ }
  };

  const updatedAgo = lastUpdated
    ? `Updated ${formatRelativeTime(lastUpdated.toISOString())}`
    : "";

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <BarChart3 size={20} />
            Analytics
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Budget, activity, and model effectiveness
            {updatedAgo && <span className="ml-2 text-xs text-muted-foreground/60">· {updatedAgo}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadData()}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent/50 transition-colors disabled:opacity-50"
          >
            <Loader2 size={14} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
          <ExportDropdown period={period} />
          <select
            value={period}
            onChange={(e) => setPeriod(Number(e.target.value))}
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
          >
            <option value={1}>Last 24h</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </div>

      {/* Observations — alerts at the top */}
      {!obsLoading && observations.length > 0 && (
        <ObservationsPanel observations={observations} onDismiss={handleDismissObservation} />
      )}

      {/* Pinned custom metrics */}
      <PinnedMetricsGrid refreshKey={pinnedRefreshKey} />

      {/* Metrics chat composer */}
      <MetricsChatPanel period={period} onMetricPinned={handleMetricPinned} />

      {/* Executive Summary — 3-bucket overview */}
      <ExecutiveSummary data={executiveSummary} />







      {/* Top row: Budget + Activity + Model Cost */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {scorecardLoading ? <SectionSkeleton height="h-48" /> : scorecardError ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400 text-sm">{scorecardError}</div>
        ) : scorecard ? <BudgetCard scorecard={scorecard} /> : null}
        {scorecardLoading ? <SectionSkeleton height="h-48" /> : scorecard ? <ActivityCard scorecard={scorecard} /> : null}
        {scorecardLoading ? <SectionSkeleton height="h-48" /> : scorecard ? <ModelCostCard scorecard={scorecard} /> : null}
      </div>

      {/* Yield / ROI + Cache Efficiency */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {yieldLoading ? <SectionSkeleton height="h-40" /> : yieldData && <YieldCard data={yieldData} />}
        {cacheLoading ? <SectionSkeleton height="h-40" /> : cacheEfficiency && <CacheEfficiencyChart data={cacheEfficiency} period={Math.max(period, 30)} />}
      </div>

      {/* Cost trend */}
      <div className="rounded-lg border border-border bg-card p-4 min-w-0">
        <h2 className="text-sm font-medium text-foreground mb-1">Cost Trend</h2>
        <p className="text-xs text-muted-foreground mb-3">Daily API-equivalent spend — for subscriptions this reflects usage value, not billing</p>
        {scorecardLoading ? <div className="h-[220px] animate-pulse bg-muted rounded" /> : scorecard ? <CostTrendChart data={scorecard.costTrend} /> : null}
      </div>

      {/* Cost Breakdown by Activity — same pattern as per-job view */}
      {!driversLoading && fleetDrivers?.summary && fleetDrivers.summary.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 min-w-0">
          <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
            <DollarSign size={14} />
            Cost Breakdown
          </h2>
          <p className="text-xs text-muted-foreground mb-3">Aggregate spend by activity across all jobs in this period</p>
          <FleetCostDriverInsights fleetDrivers={fleetDrivers} period={period} />
        </div>
      )}

      {/* Latency Breakdown — parallel to cost breakdown */}
      {!latencyLoading && fleetLatency?.summary && fleetLatency.summary.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 min-w-0">
          <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
            <Clock size={14} />
            Latency Breakdown
          </h2>
          <p className="text-xs text-muted-foreground mb-3">Where wall-clock time goes — by activity, with LLM vs tool split</p>
          <FleetLatencyDriverInsights fleetLatency={fleetLatency} />
        </div>
      )}

      {/* Model Comparison */}
      <div className="rounded-lg border border-border bg-card p-4 min-w-0">
        <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
          <Zap size={14} />
          Model Comparison
        </h2>
        <p className="text-xs text-muted-foreground mb-3">Cost, speed, and outcomes per model — use this to pick models for future jobs</p>
        {modelLoading ? <div className="h-[200px] animate-pulse bg-muted rounded" /> : modelComparison && <ModelComparison data={modelComparison} repos={repos} selectedRepo={selectedRepo} onRepoChange={setSelectedRepo} modelEfficiency={modelEfficiency ?? undefined} />}
      </div>

      {/* Repo breakdown */}
      <div className="rounded-lg border border-border bg-card p-4 min-w-0">
        <h2 className="text-sm font-medium text-foreground mb-3 flex items-center gap-2">
          <GitBranch size={14} />
          Repository Breakdown
        </h2>
        {reposLoading ? <div className="h-[200px] animate-pulse bg-muted rounded" /> : repos && <RepoBreakdown repos={repos.repos} />}
      </div>

      {/* Recent jobs — compact preview, link to full history */}
      <RecentJobsPreview period={period} />

      <CollapsibleSection title="Tool Health" icon={Wrench}>
        {toolsLoading ? <div className="h-[100px] animate-pulse bg-muted rounded" /> : tools && <ToolHealth tools={tools.tools} />}
      </CollapsibleSection>

    </div>
  );
}
