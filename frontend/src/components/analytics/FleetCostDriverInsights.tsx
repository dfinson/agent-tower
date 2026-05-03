import { useMemo, useState } from "react";
import { Tooltip } from "../ui/tooltip";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, type TooltipValueType,
} from "recharts";
import { type FleetCostDriversResponse } from "../../api/client";
import { formatUsd } from "./helpers";
import { cn } from "../../lib/utils";

// ---------------------------------------------------------------------------
// Shared label / description maps
// ---------------------------------------------------------------------------

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
  debugging: "Debugging",
  refactoring: "Refactoring",
  feature_dev: "Feature Dev",
  testing: "Testing",
  git_ops: "Git Ops",
  build_deploy: "Build / Deploy",
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

const phaseColors: Record<string, string> = {
  environment_setup: "bg-cyan-500",
  agent_reasoning: "bg-blue-500",
  verification: "bg-amber-500",
  finalization: "bg-purple-500",
  post_completion: "bg-slate-400",
};

const phaseShortLabels: Record<string, string> = {
  environment_setup: "Setup",
  agent_reasoning: "Reasoning",
  verification: "Verify",
  finalization: "Final",
  post_completion: "Post",
};

// ---------------------------------------------------------------------------
// Fleet cost driver insights — unified view
// ---------------------------------------------------------------------------

export function FleetCostDriverInsights({ fleetDrivers }: { fleetDrivers: FleetCostDriversResponse }) {
  const summary = useMemo(() => fleetDrivers.summary ?? [], [fleetDrivers.summary]);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const activityRows = useMemo(
    () => summary.filter((row) => row.dimension === "activity").sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 10),
    [summary],
  );

  // Build phase breakdown per activity from activity_phase compound rows
  const phasesByActivity = useMemo(() => {
    const apRows = summary.filter((row) => row.dimension === "activity_phase");
    const map: Record<string, { phase: string; costUsd: number; jobCount: number }[]> = {};
    for (const row of apRows) {
      const sep = row.bucket.lastIndexOf(":");
      if (sep < 0) continue;
      const activity = row.bucket.slice(0, sep);
      const phase = row.bucket.slice(sep + 1);
      if (!map[activity]) map[activity] = [];
      map[activity].push({ phase, costUsd: row.cost_usd, jobCount: row.job_count ?? 0 });
    }
    for (const phases of Object.values(map)) {
      phases.sort((a, b) => b.costUsd - a.costUsd);
    }
    return map;
  }, [summary]);

  const toggleRow = (bucket: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  };

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
                  const phases = phasesByActivity[row.bucket] ?? [];
                  const hasPhases = phases.length > 0;
                  const isExpanded = expandedRows.has(row.bucket);
                  return (
                  <tr key={i} className="border-b border-border/50 hover:bg-accent/30 group" onClick={hasPhases ? () => toggleRow(row.bucket) : undefined}>
                    <td className={cn("py-1.5 px-2", hasPhases && "cursor-pointer")}>
                      <div className="flex items-center gap-1">
                        {hasPhases && (
                          isExpanded
                            ? <ChevronDown size={10} className="shrink-0 text-muted-foreground" />
                            : <ChevronRight size={10} className="shrink-0 text-muted-foreground" />
                        )}
                        {desc ? <Tooltip content={desc}><span className="cursor-help border-b border-dotted border-muted-foreground/50">{label}</span></Tooltip> : label}
                      </div>
                      {/* Inline phase proportion bar */}
                      {phases.length > 0 && (
                        <Tooltip content={phases.map((p) => `${phaseShortLabels[p.phase] ?? p.phase}: ${formatUsd(p.costUsd)}`).join(" · ")}>
                          <div className="h-1 rounded-full bg-muted overflow-hidden flex mt-1 max-w-[120px]">
                            {phases.map((p) => {
                              const pPct = row.cost_usd > 0 ? (p.costUsd / row.cost_usd) * 100 : 0;
                              return (
                                <div key={p.phase} className={cn("h-full", phaseColors[p.phase] ?? "bg-gray-400")} style={{ width: `${Math.max(pPct, 3)}%` }} />
                              );
                            })}
                          </div>
                        </Tooltip>
                      )}
                    </td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.cost_usd) || 0)}</td>
                    <td className="text-right py-1.5 px-2">{row.call_count}</td>
                    <td className="text-right py-1.5 px-2">{row.job_count ?? "—"}</td>
                    <td className="text-right py-1.5 px-2">{formatUsd(Number(row.avg_cost_per_job) || 0)}</td>
                  </tr>
                  );})}
                {/* Expanded phase detail rows */}
                {activityRows.map((row) => {
                  if (!expandedRows.has(row.bucket)) return null;
                  const phases = phasesByActivity[row.bucket] ?? [];
                  return phases.map((p) => (
                    <tr key={`${row.bucket}:${p.phase}`} className="border-b border-border/30 bg-accent/10">
                      <td className="py-1 px-2 pl-7 text-muted-foreground">
                        <div className="flex items-center gap-1.5">
                          <div className={cn("w-2 h-2 rounded-full shrink-0", phaseColors[p.phase] ?? "bg-gray-400")} />
                          {phaseShortLabels[p.phase] ?? p.phase.replace(/_/g, " ")}
                        </div>
                      </td>
                      <td className="text-right py-1 px-2 text-muted-foreground">{formatUsd(p.costUsd)}</td>
                      <td className="text-right py-1 px-2 text-muted-foreground">—</td>
                      <td className="text-right py-1 px-2 text-muted-foreground">{p.jobCount || "—"}</td>
                      <td className="text-right py-1 px-2 text-muted-foreground">—</td>
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>

          {/* Phase legend */}
          {Object.keys(phasesByActivity).length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1">
              {Object.entries(phaseShortLabels).map(([phase, label]) => (
                <div key={phase} className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <div className={cn("w-2 h-2 rounded-full", phaseColors[phase] ?? "bg-gray-400")} />
                  {label}
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No cost-driver data yet.</p>
      )}
    </div>
  );
}
