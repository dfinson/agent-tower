import { DollarSign, AlertTriangle } from "lucide-react";
import { Tooltip } from "../ui/tooltip";
import { type ScorecardResponse } from "../../api/client";
import { Badge } from "../ui/badge";
import { formatUsd, formatDuration } from "./helpers";

// ---------------------------------------------------------------------------
// Budget card — adapts per SDK
// ---------------------------------------------------------------------------

export function BudgetCard({ scorecard }: { scorecard: ScorecardResponse }) {
  const { budget, quotaJson, dailySpendLimitUsd, costTrend } = scorecard;
  const totalCost = budget.reduce((s, b) => s + b.totalCostUsd, 0);
  const totalJobs = budget.reduce((s, b) => s + b.jobCount, 0);

  // Today's spend from costTrend (last entry is today/most recent day)
  const todaysCost = costTrend.length > 0 ? Number(costTrend[costTrend.length - 1]?.cost ?? 0) : 0;
  const dailyLimit = dailySpendLimitUsd || 0;
  const dailyPct = dailyLimit > 0 ? (todaysCost / dailyLimit) * 100 : 0;

  let quotaInfo: { pct: number } | null = null;
  if (quotaJson) {
    try {
      const q = JSON.parse(quotaJson);
      const snapshots = Array.isArray(q) ? q : q?.snapshots ?? [q];
      const latest = snapshots[snapshots.length - 1];
      if (latest && typeof latest.percentage_used === "number") {
        quotaInfo = { pct: latest.percentage_used };
      } else if (latest && latest.used != null && latest.total != null && latest.total > 0) {
        quotaInfo = { pct: (latest.used / latest.total) * 100 };
      }
    } catch { /* ignore malformed quota */ }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <DollarSign size={14} />
        Budget
      </div>

      <div className="text-2xl font-semibold text-foreground">
        <Tooltip content={`API-equivalent cost across ${totalJobs} jobs. For subscription plans (Claude Max, Copilot Pro), this reflects what the same usage would cost at API rates — not your subscription charge.`}>
          <span className="cursor-help">{formatUsd(totalCost)}</span>
        </Tooltip>
      </div>

      <div className="space-y-2">
        {budget.map((b) => (
          <div key={b.sdk} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <Badge variant="outline" className="text-[10px]">{b.sdk}</Badge>
              <span className="text-muted-foreground">{b.jobCount} jobs</span>
            </div>
            <div className="flex items-center gap-3">
              {b.totalCostUsd > 0 || b.avgCostPerJob > 0 ? (
                <Tooltip content={`API-equivalent cost: ${formatUsd(b.avgCostPerJob)} avg per job, ${formatDuration(b.avgDurationMs)} avg duration. For subscriptions this reflects usage value, not your actual charge.`}>
                  <span className="cursor-help text-foreground">{formatUsd(b.totalCostUsd)}</span>
                </Tooltip>
              ) : (
                <span className="text-muted-foreground italic">No usage data</span>
              )}
              {b.premiumRequests > 0 && (
                <Tooltip content="Premium requests consumed from your Copilot entitlement this period">
                  <span className="cursor-help text-muted-foreground">{b.premiumRequests} reqs</span>
                </Tooltip>
              )}
            </div>
          </div>
        ))}
      </div>

      {dailyLimit > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-muted-foreground">Daily Limit</span>
            <span className={dailyPct > 80 ? "text-red-400 font-medium" : "text-foreground"}>
              {formatUsd(todaysCost)} / {formatUsd(dailyLimit)}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                dailyPct > 80 ? "bg-red-500" : dailyPct > 60 ? "bg-yellow-500" : "bg-green-500"
              }`}
              style={{ width: `${Math.min(dailyPct, 100)}%` }}
            />
          </div>
          {dailyPct > 80 && (
            <div className="flex items-center gap-1 mt-1 text-[11px] text-red-400">
              <AlertTriangle size={11} />
              Approaching daily limit
            </div>
          )}
        </div>
      )}

      {quotaInfo && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-muted-foreground">Copilot Quota</span>
            <span className={(quotaInfo.pct ?? 0) > 80 ? "text-red-400 font-medium" : "text-foreground"}>
              {(quotaInfo.pct ?? 0).toFixed(0)}% used
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                quotaInfo.pct > 80 ? "bg-red-500" : quotaInfo.pct > 60 ? "bg-yellow-500" : "bg-green-500"
              }`}
              style={{ width: `${Math.min(quotaInfo.pct, 100)}%` }}
            />
          </div>
          {quotaInfo.pct > 80 && (
            <div className="flex items-center gap-1 mt-1 text-[11px] text-red-400">
              <AlertTriangle size={11} />
              Approaching quota limit
            </div>
          )}
        </div>
      )}

      {scorecard.monthlyBudgetUsd > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-muted-foreground">Monthly Budget</span>
            <span className={scorecard.pctMonthlyBudgetUsed > 0.8 ? "text-red-400 font-medium" : "text-foreground"}>
              {formatUsd(scorecard.monthSpendUsd)} / {formatUsd(scorecard.monthlyBudgetUsd)}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-border overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                scorecard.pctMonthlyBudgetUsed > 0.8
                  ? "bg-red-500"
                  : scorecard.pctMonthlyBudgetUsed > 0.6
                  ? "bg-yellow-500"
                  : "bg-green-500"
              }`}
              style={{ width: `${Math.min(scorecard.pctMonthlyBudgetUsed * 100, 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground mt-1">
            <span>Day {scorecard.daysElapsed} of {scorecard.daysInMonth}</span>
            <Tooltip content={`At ${formatUsd(scorecard.dailyAvgUsd)}/day average, projected month-end total`}>
              <span className="cursor-help">Proj: {formatUsd(scorecard.projectedMonthEndUsd)}</span>
            </Tooltip>
          </div>
          {scorecard.pctMonthlyBudgetUsed > 0.8 && (
            <div className="flex items-center gap-1 mt-1 text-[11px] text-red-400">
              <AlertTriangle size={11} />
              Approaching monthly budget
            </div>
          )}
          {scorecard.projectedMonthEndUsd > scorecard.monthlyBudgetUsd && (
            <div className="flex items-center gap-1 mt-1 text-[11px] text-red-400">
              <AlertTriangle size={11} />
              Projected month-end: {formatUsd(scorecard.projectedMonthEndUsd)} (exceeds {formatUsd(scorecard.monthlyBudgetUsd)} budget by {Math.round(((scorecard.projectedMonthEndUsd - scorecard.monthlyBudgetUsd) / scorecard.monthlyBudgetUsd) * 100)}%)
            </div>
          )}
        </div>
      )}

      {/* Cost per line of code */}
      {scorecard.costPerDiffLine != null && scorecard.costPerDiffLine > 0 && (
        <div className="pt-2 border-t border-border">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Cost per line</span>
            <span className="text-foreground font-medium">
              ${scorecard.costPerDiffLine.toFixed(4)} / line
              {scorecard.totalDiffLines != null && (
                <span className="text-muted-foreground font-normal ml-1">
                  ({scorecard.totalDiffLines.toLocaleString()} lines changed)
                </span>
              )}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
