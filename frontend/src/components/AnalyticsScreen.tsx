import { useState, useEffect } from "react";
import {
  BarChart3, DollarSign, Clock, Wrench, GitBranch, Zap, Loader2,
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
  type ScorecardResponse,
  type ModelComparisonResponse,
  type AnalyticsTools,
  type AnalyticsRepos,
  type FleetCostDriversResponse,
  type FleetLatencyDriversResponse,
  type Observation,
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
  ToolMix,
  FleetCostDriverInsights,
  FleetLatencyDriverInsights,
  JobsTable,
} from "./AnalyticsWidgets";

export function AnalyticsScreen() {
  const [period, setPeriod] = useState(7);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [scorecard, setScorecard] = useState<ScorecardResponse | null>(null);
  const [modelComparison, setModelComparison] = useState<ModelComparisonResponse | null>(null);
  const [tools, setTools] = useState<AnalyticsTools | null>(null);
  const [repos, setRepos] = useState<AnalyticsRepos | null>(null);
  const [fleetDrivers, setFleetDrivers] = useState<FleetCostDriversResponse | null>(null);
  const [fleetLatency, setFleetLatency] = useState<FleetLatencyDriversResponse | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);

  // Per-section loading states
  const [scorecardLoading, setScorecardLoading] = useState(true);
  const [modelLoading, setModelLoading] = useState(true);
  const [toolsLoading, setToolsLoading] = useState(true);
  const [reposLoading, setReposLoading] = useState(true);
  const [driversLoading, setDriversLoading] = useState(true);
  const [latencyLoading, setLatencyLoading] = useState(true);
  const [obsLoading, setObsLoading] = useState(true);

  const [scorecardError, setScorecardError] = useState<string | null>(null);

  // Timestamp of last successful data load
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);

    setScorecardLoading(true);
    setModelLoading(true);
    setToolsLoading(true);
    setReposLoading(true);
    setDriversLoading(true);
    setLatencyLoading(true);
    setObsLoading(true);
    setScorecardError(null);

    // Fire all fetches independently
    fetchScorecard(period)
      .then((sc) => { setScorecard(sc); setLastUpdated(new Date()); })
      .catch((err) => setScorecardError(err.message || "Failed to load scorecard"))
      .finally(() => { setScorecardLoading(false); if (isRefresh) setRefreshing(false); });

    fetchModelComparison(Math.max(period, 30), selectedRepo || undefined)
      .then(setModelComparison)
      .catch(() => {})
      .finally(() => setModelLoading(false));

    fetchAnalyticsTools(Math.max(period, 30))
      .then(setTools)
      .catch(() => {})
      .finally(() => setToolsLoading(false));

    fetchAnalyticsRepos(period)
      .then(setRepos)
      .catch(() => {})
      .finally(() => setReposLoading(false));

    fetchFleetCostDrivers(Math.max(period, 30))
      .then(setFleetDrivers)
      .catch(() => setFleetDrivers(null))
      .finally(() => setDriversLoading(false));

    fetchFleetLatencyDrivers(Math.max(period, 30))
      .then(setFleetLatency)
      .catch(() => setFleetLatency(null))
      .finally(() => setLatencyLoading(false));

    fetchObservations()
      .then((obs) => setObservations(obs?.observations ?? []))
      .catch(() => {})
      .finally(() => setObsLoading(false));
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, selectedRepo]);

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
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground hover:bg-accent/50 transition-colors disabled:opacity-50"
          >
            <Loader2 size={14} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
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

      {/* Top row: Budget + Activity */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {scorecardLoading ? <SectionSkeleton height="h-48" /> : scorecardError ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400 text-sm">{scorecardError}</div>
        ) : scorecard ? <BudgetCard scorecard={scorecard} /> : null}
        {scorecardLoading ? <SectionSkeleton height="h-48" /> : scorecard ? <ActivityCard scorecard={scorecard} /> : null}
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
          <FleetCostDriverInsights fleetDrivers={fleetDrivers} />
        </div>
      )}

      {/* Latency Breakdown — parallel to cost breakdown */}
      {!latencyLoading && fleetLatency?.summary && fleetLatency.summary.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 min-w-0">
          <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
            <Clock size={14} />
            Latency Breakdown
          </h2>
          <p className="text-xs text-muted-foreground mb-3">Where wall-clock time goes — LLM wait, tool execution, idle overhead</p>
          <FleetLatencyDriverInsights fleetLatency={fleetLatency} />
        </div>
      )}

      {/* Tool Mix — percentage breakdown by category */}
      {!toolsLoading && tools?.toolMix && tools.toolMix.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4 min-w-0">
          <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
            <Wrench size={14} />
            Tool Mix
          </h2>
          <p className="text-xs text-muted-foreground mb-3">
            Tool usage by category across {tools.toolMixJobCount?.toLocaleString() ?? "all"} jobs
          </p>
          <ToolMix mix={tools.toolMix} />
        </div>
      )}

      {/* Model Comparison */}
      <div className="rounded-lg border border-border bg-card p-4 min-w-0">
        <h2 className="text-sm font-medium text-foreground mb-1 flex items-center gap-2">
          <Zap size={14} />
          Model Comparison
        </h2>
        <p className="text-xs text-muted-foreground mb-3">Cost, speed, and outcomes per model — use this to pick models for future jobs</p>
        {modelLoading ? <div className="h-[200px] animate-pulse bg-muted rounded" /> : modelComparison && <ModelComparison data={modelComparison} repos={repos} selectedRepo={selectedRepo} onRepoChange={setSelectedRepo} />}
      </div>

      {/* Repo breakdown */}
      <div className="rounded-lg border border-border bg-card p-4 min-w-0">
        <h2 className="text-sm font-medium text-foreground mb-3 flex items-center gap-2">
          <GitBranch size={14} />
          Repository Breakdown
        </h2>
        {reposLoading ? <div className="h-[200px] animate-pulse bg-muted rounded" /> : repos && <RepoBreakdown repos={repos.repos} />}
      </div>

      {/* Collapsed detail sections */}
      <CollapsibleSection title="Recent Jobs" icon={Clock}>
        <JobsTable period={period} />
      </CollapsibleSection>

      <CollapsibleSection title="Tool Health" icon={Wrench}>
        {toolsLoading ? <div className="h-[100px] animate-pulse bg-muted rounded" /> : tools && <ToolHealth tools={tools.tools} />}
      </CollapsibleSection>

    </div>
  );
}
