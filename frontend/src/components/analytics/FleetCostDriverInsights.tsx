import { useMemo } from "react";
import { Tooltip } from "../ui/tooltip";
import {
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, type TooltipValueType,
} from "recharts";
import { type FleetCostDriversResponse } from "../../api/client";
import { formatUsd } from "./helpers";

// ---------------------------------------------------------------------------
// Fleet cost driver insights
// ---------------------------------------------------------------------------

export function FleetCostDriverInsights({ fleetDrivers }: { fleetDrivers: FleetCostDriversResponse }) {
  const summary = useMemo(() => fleetDrivers.summary ?? [], [fleetDrivers.summary]);

  const activityLabels: Record<string, string> = {
    command_execution: "Command Execution",
    code_reading: "Code Reading",
    reasoning: "Reasoning",
    user_communication: "User Messages",
    code_changes: "Code Changes",
    delegation: "Delegation",
    search_discovery: "Search & Discovery",
    other_tools: "Other Tools",
    bookkeeping: "Bookkeeping",
    // Intent-refined activity categories
    debugging: "Debugging",
    refactoring: "Refactoring",
    feature_dev: "Feature Dev",
    testing: "Testing",
    git_ops: "Git Ops",
    build_deploy: "Build / Deploy",
    // Phase dimension values
    environment_setup: "Setup",
    agent_reasoning: "Reasoning",
    verification: "Verification",
    finalization: "Finalization",
    post_completion: "Post-completion",
  };
  const activityDescriptions: Record<string, string> = {
    command_execution: "LLM cost for turns where the agent ran shell commands (bash, terminal, sql)",
    code_reading: "LLM cost for turns where the agent read files or checked git status/diffs",
    reasoning: "LLM cost for explicit thinking (Think tool) with no user-facing output",
    user_communication: "LLM cost for turns where the agent composed a message to you (no tool calls)",
    code_changes: "LLM cost for turns where the agent edited/created files or committed git changes",
    delegation: "LLM cost for turns where the agent delegated to sub-agents",
    search_discovery: "LLM cost for turns where the agent searched code or fetched URLs",
    other_tools: "LLM cost for turns using unclassified or custom tools",
    bookkeeping: "LLM cost for turns where the agent managed todos, memory, or intent",
    debugging: "LLM cost for turns where the agent fixed bugs, errors, or failing code",
    refactoring: "LLM cost for turns where the agent restructured, renamed, or simplified code",
    feature_dev: "LLM cost for turns where the agent built new features or scaffolded components",
    testing: "LLM cost for turns where the agent ran or wrote tests",
    git_ops: "LLM cost for turns where the agent ran git commands (push, commit, merge, etc.)",
    build_deploy: "LLM cost for turns where the agent ran build, install, or deploy commands",
  };

  const activityRows = useMemo(
    () => summary.filter((row) => row.dimension === "activity").sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 10),
    [summary],
  );

  const phaseRows = useMemo(
    () => summary.filter((row) => row.dimension === "phase").sort((a, b) => b.cost_usd - a.cost_usd),
    [summary],
  );

  return (
    <div className="space-y-3">
      {activityRows.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={activityRows.map((row) => ({ name: activityLabels[row.bucket] || row.bucket, cost: row.cost_usd }))} margin={{ top: 5, right: 10, left: 0, bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#888" }} interval={0} angle={-20} textAnchor="end" height={55} />
              <YAxis tick={{ fontSize: 11, fill: "#888" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <RTooltip
                contentStyle={{ background: "#1a1a2e", border: "1px solid #333", borderRadius: 8, fontSize: 12 }}
                formatter={(v: TooltipValueType | undefined) => [formatUsd(Number(v ?? 0)), "Cost"]}
              />
              <Bar dataKey="cost" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground border-b border-border">
                  <th className="text-left py-1.5 px-2 font-medium">Activity</th>
                  <th className="text-right py-1.5 px-2 font-medium">Cost</th>
                  <th className="text-right py-1.5 px-2 font-medium">Calls</th>
                  <th className="text-right py-1.5 px-2 font-medium">Jobs</th>
                  <th className="text-right py-1.5 px-2 font-medium">Avg/Job</th>
                </tr>
              </thead>
              <tbody>
                {activityRows.map((row, i) => {
                  const label = activityLabels[row.bucket] || row.bucket;
                  const desc = activityDescriptions[row.bucket];
                  return (
                  <tr key={i} className="border-b border-border/50 hover:bg-accent/30">
                    <td className="py-1.5 px-2">
                      {desc ? <Tooltip content={desc}><span className="cursor-help border-b border-dotted border-muted-foreground/50">{label}</span></Tooltip> : label}
                      {row.confidence === "approximate" && (
                        <Tooltip content="Activity cost is estimated using an equal-weight heuristic — the actual split may differ">
                          <span className="ml-1 text-[10px] text-muted-foreground cursor-help">~approx</span>
                        </Tooltip>
                      )}
                    </td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.cost_usd) || 0)}</td>
                    <td className="text-right py-1.5 px-2">{row.call_count}</td>
                    <td className="text-right py-1.5 px-2">{row.job_count ?? "—"}</td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.avg_cost_per_job) || 0)}</td>
                  </tr>
                  );})}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No cost-driver data yet.</p>
      )}

      {phaseRows.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Cost by Execution Phase</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-muted-foreground border-b border-border">
                  <th className="text-left py-1.5 px-2 font-medium">Phase</th>
                  <th className="text-right py-1.5 px-2 font-medium">Cost</th>
                  <th className="text-right py-1.5 px-2 font-medium">Jobs</th>
                  <th className="text-right py-1.5 px-2 font-medium">Avg/Job</th>
                </tr>
              </thead>
              <tbody>
                {phaseRows.map((row, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-accent/30">
                    <td className="py-1.5 px-2">{activityLabels[row.bucket] || row.bucket.replace(/_/g, " ")}</td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.cost_usd) || 0)}</td>
                    <td className="text-right py-1.5 px-2">{row.job_count ?? "—"}</td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.avg_cost_per_job) || 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
