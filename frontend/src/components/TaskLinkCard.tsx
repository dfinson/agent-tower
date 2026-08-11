import { memo } from "react";
import { Link2, Clock3, CheckCircle2 } from "lucide-react";
import type { TaskLinkResponse } from "../api/types";
import { pathBasename } from "../lib/paths";
import { Tooltip } from "./ui/tooltip";

interface TaskLinkCardProps {
  taskLink: TaskLinkResponse;
  /** True when every `dependsOn` entry is satisfied (empty list counts as satisfied). */
  satisfied: boolean;
  /** Human-readable label for the first unsatisfied dependency, when `satisfied` is false. */
  blockingLabel?: string | null;
}

/**
 * A TaskLink recipe-chain card (Story 4.4 / CAP-10). Rendered alongside regular
 * `JobCard`s in the same column grid — never a separate screen. Greyed out with
 * a "waiting on …" badge when its `dependsOn` list has unsatisfied entries;
 * normal styling once every dependency is satisfied (ready to spawn, or already
 * linked to a running `jobId`).
 */
export const TaskLinkCard = memo(function TaskLinkCard({ taskLink, satisfied, blockingLabel }: TaskLinkCardProps) {
  const repoName = pathBasename(taskLink.repoPath) || taskLink.repoPath;
  const label = taskLink.storyNodeId ?? taskLink.trackerTicketRef ?? taskLink.id;

  return (
    <div
      className={`w-full shrink-0 text-left rounded-lg border border-border bg-background p-3 overflow-hidden transition-opacity ${
        satisfied ? "" : "opacity-60"
      }`}
      aria-label={`Task recipe: ${label} — ${satisfied ? "dependencies satisfied" : "waiting on dependencies"}`}
    >
      <div className="flex justify-between items-start gap-2 mb-1.5">
        <span className="text-sm font-semibold text-primary flex-1 min-w-0 break-words line-clamp-2 flex items-center gap-1.5" title={label}>
          <Link2 size={13} className="text-muted-foreground shrink-0" aria-hidden="true" />
          {label}
        </span>
        {satisfied ? (
          <Tooltip content="Every dependency is satisfied — ready to spawn or already linked to a running job">
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/15 text-emerald-600 px-1.5 py-0.5 text-xs font-medium">
              <CheckCircle2 size={10} />
              deps satisfied
            </span>
          </Tooltip>
        ) : (
          <Tooltip content={blockingLabel ? `Waiting on "${blockingLabel}"` : "Waiting on an unsatisfied dependency"}>
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/15 text-amber-600 px-1.5 py-0.5 text-xs font-medium">
              <Clock3 size={10} />
              {blockingLabel ? `waiting on ${blockingLabel}` : "waiting"}
            </span>
          </Tooltip>
        )}
      </div>

      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center rounded-full border border-border px-1.5 py-0.5 uppercase tracking-wide text-[10px] font-semibold">
          chained
        </span>
        <span className="font-mono truncate" title={taskLink.repoPath}>{repoName}</span>
      </div>
    </div>
  );
});
