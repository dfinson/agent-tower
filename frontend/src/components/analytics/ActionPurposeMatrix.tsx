import { Grid3X3, Info } from "lucide-react";
import { type ActionPurposeMatrixResponse } from "../../api/client-analytics";
import { formatUsd } from "./helpers";

const ACTIONS = ["write", "test", "execute", "vcs", "delegate", "read", "think"] as const;
const PURPOSES = ["building", "recovering", "orienting", "verifying", "housekeeping"] as const;

const PURPOSE_COLORS: Record<string, string> = {
  building: "bg-green-500",
  recovering: "bg-red-500",
  orienting: "bg-blue-500",
  verifying: "bg-amber-500",
  housekeeping: "bg-gray-400",
};

const PURPOSE_LABELS: Record<string, string> = {
  building: "Building",
  recovering: "Recovering",
  orienting: "Orienting",
  verifying: "Verifying",
  housekeeping: "Housekeeping",
};

const PURPOSE_DESCRIPTIONS: Record<string, string> = {
  building: "Producing artifacts toward the goal — writing code, creating files, making progress",
  recovering: "Fixing mistakes or retrying failed attempts — undoing errors, debugging regressions",
  orienting: "Understanding code and context — reading docs, searching, exploring the codebase",
  verifying: "Confirming correctness — running tests, checking output, validating behavior",
  housekeeping: "Cleanup and bookkeeping — formatting, linting, updating configs, organizing",
};

const ACTION_LABELS: Record<string, string> = {
  write: "Write",
  test: "Test",
  execute: "Execute",
  vcs: "VCS",
  delegate: "Delegate",
  read: "Read",
  think: "Think",
};

const ACTION_DESCRIPTIONS: Record<string, string> = {
  write: "File edits and creation — the agent is changing code or creating new files",
  test: "Running test suites — pytest, vitest, jest, or other test frameworks",
  execute: "Shell commands — builds, installs, scripts (excluding tests and git)",
  vcs: "Git operations — commits, diffs, status checks, branch management",
  delegate: "Sub-agent calls — spawning specialized agents for sub-tasks",
  read: "Reading and searching — viewing files, grepping, browsing documentation",
  think: "Reasoning and planning — internal deliberation with no tool output",
};

interface Props {
  data: ActionPurposeMatrixResponse | null;
}

export function ActionPurposeMatrix({ data }: Props) {
  if (!data?.cells?.length) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
          <Grid3X3 size={14} />
          Action × Purpose
        </div>
        <p className="text-muted-foreground text-sm mt-2">No action×purpose data yet.</p>
      </div>
    );
  }

  // Build lookup: action:purpose → costUsd
  const lookup: Record<string, number> = {};
  let maxCost = 0;
  for (const cell of data.cells) {
    const key = `${cell.action}:${cell.purpose}`;
    lookup[key] = (lookup[key] ?? 0) + cell.costUsd;
    if (lookup[key]! > maxCost) maxCost = lookup[key]!;
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Grid3X3 size={14} />
        Action × Purpose
        <span
          className="cursor-help"
          title="How much was spent on each type of agent activity (rows) broken down by why the agent was doing it (columns). High spend in Recovering suggests the agent is wasting money fixing its own mistakes."
        >
          <Info size={12} className="text-muted-foreground/60" />
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th
                className="text-left px-2 py-1 text-muted-foreground font-medium"
                title="What the agent was doing (the type of tool call)"
              />
              {PURPOSES.map((p) => (
                <th
                  key={p}
                  className="text-center px-2 py-1 text-muted-foreground font-medium cursor-help"
                  title={PURPOSE_DESCRIPTIONS[p]}
                >
                  <div className="flex items-center justify-center gap-1">
                    <span className={`w-2 h-2 rounded ${PURPOSE_COLORS[p]}`} />
                    {PURPOSE_LABELS[p]}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ACTIONS.map((action) => {
              const hasData = PURPOSES.some((p) => lookup[`${action}:${p}`]);
              if (!hasData) return null;
              return (
                <tr key={action} className="border-t border-border/50">
                  <td
                    className="px-2 py-1.5 font-medium text-foreground cursor-help"
                    title={ACTION_DESCRIPTIONS[action]}
                  >
                    {ACTION_LABELS[action]}
                  </td>
                  {PURPOSES.map((purpose) => {
                    const cost = lookup[`${action}:${purpose}`] ?? 0;
                    const intensity = maxCost > 0 ? cost / maxCost : 0;
                    return (
                      <td key={purpose} className="px-2 py-1.5 text-center">
                        {cost > 0 ? (
                          <span
                            className="inline-block rounded px-1.5 py-0.5 cursor-help"
                            style={{
                              backgroundColor: `rgba(var(--color-primary-rgb, 59, 130, 246), ${intensity * 0.3 + 0.05})`,
                            }}
                            title={`${formatUsd(cost)} spent on "${ACTION_LABELS[action]}" actions while "${PURPOSE_LABELS[purpose]}"\n\n${ACTION_DESCRIPTIONS[action]}\n${PURPOSE_DESCRIPTIONS[purpose]}`}
                          >
                            {formatUsd(cost)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground/40">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
