import { memo } from "react";
import { CheckCircle2, CirclePlay, Clock3, Link2, Loader2, XCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { TaskLinkResponse } from "../api/types";
import { pathBasename } from "../lib/paths";
import { Button } from "./ui/button";

interface TaskLinkCardProps {
  taskLink: TaskLinkResponse;
  starting?: boolean;
  onStart?: (taskLink: TaskLinkResponse) => void;
}

const stateStyle = {
  waiting: "border-amber-500/30 bg-amber-500/15 text-amber-600",
  ready: "border-sky-500/30 bg-sky-500/15 text-sky-600",
  running: "border-indigo-500/30 bg-indigo-500/15 text-indigo-600",
  completed: "border-emerald-500/30 bg-emerald-500/15 text-emerald-600",
  failed: "border-red-500/30 bg-red-500/15 text-red-600",
} as const;

function StateIcon({ state }: { state: TaskLinkResponse["state"] }) {
  if (state === "completed") return <CheckCircle2 size={11} />;
  if (state === "failed") return <XCircle size={11} />;
  if (state === "running") return <Loader2 size={11} className="animate-spin" />;
  if (state === "ready") return <CirclePlay size={11} />;
  return <Clock3 size={11} />;
}

export const TaskLinkCard = memo(function TaskLinkCard({
  taskLink,
  starting = false,
  onStart,
}: TaskLinkCardProps) {
  const navigate = useNavigate();
  const repoName = pathBasename(taskLink.repoPath) || taskLink.repoPath;
  const label = taskLink.storyNodeId ?? taskLink.trackerTicketRef ?? taskLink.id;
  const source = taskLink.storyNodeId
    ? `Story ${taskLink.storyNodeId}`
    : `Tracker ${taskLink.trackerTicketRef}`;
  const navigable = Boolean(taskLink.jobId);

  const openJob = () => {
    if (taskLink.jobId) navigate(`/jobs/${taskLink.jobId}`);
  };

  return (
    <div
      className={`w-full shrink-0 rounded-lg border border-border bg-background p-3 overflow-hidden ${
        taskLink.state === "waiting" ? "opacity-60" : ""
      } ${navigable ? "cursor-pointer hover:border-primary/40" : ""}`}
      aria-label={`Task recipe: ${label} — ${taskLink.state}`}
      role={navigable ? "link" : undefined}
      tabIndex={navigable ? 0 : undefined}
      onClick={openJob}
      onKeyDown={(event) => {
        if (navigable && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          openJob();
        }
      }}
    >
      <div className="flex justify-between items-start gap-2 mb-2">
        <span className="text-sm font-semibold text-primary flex-1 min-w-0 break-words line-clamp-2 flex items-center gap-1.5">
          <Link2 size={13} className="text-muted-foreground shrink-0" aria-hidden="true" />
          {label}
        </span>
        <span className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs font-medium ${stateStyle[taskLink.state]}`}>
          <StateIcon state={taskLink.state} />
          {taskLink.state}
        </span>
      </div>

      <dl className="space-y-1 text-xs text-muted-foreground">
        <div className="flex gap-1.5"><dt className="font-medium">Source:</dt><dd>{source}</dd></div>
        <div className="flex gap-1.5">
          <dt className="font-medium">Dependencies:</dt>
          <dd>{taskLink.dependsOn.length ? taskLink.dependsOn.map((dep) => dep.split("::").pop()).join(", ") : "None"}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="font-medium">Job:</dt>
          <dd>{taskLink.jobId ?? "Not started"}</dd>
        </div>
        {taskLink.trackerLinkId && (
          <div className="flex gap-1.5"><dt className="font-medium">Tracker link:</dt><dd>{taskLink.trackerLinkId}</dd></div>
        )}
      </dl>

      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground truncate" title={taskLink.repoPath}>{repoName}</span>
        {taskLink.state === "ready" && !taskLink.jobId && onStart && (
          <Button
            size="sm"
            disabled={starting}
            onClick={(event) => {
              event.stopPropagation();
              onStart(taskLink);
            }}
          >
            {starting ? <Loader2 size={13} className="animate-spin" /> : <CirclePlay size={13} />}
            Start task
          </Button>
        )}
      </div>
    </div>
  );
});
