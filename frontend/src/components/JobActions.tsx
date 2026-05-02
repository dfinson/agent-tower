import { RotateCcw, XCircle, CheckCircle2, GitMerge, GitPullRequest, Trash2, Archive } from "lucide-react";
import { Button } from "./ui/button";
import { Tooltip } from "./ui/tooltip";

export interface JobActionsProps {
  canCancel: boolean;
  canResume: boolean;
  needsResolution: boolean;
  hasChanges: boolean;
  hasMergeConflict: boolean;
  isResolved: boolean;
  canArchive: boolean;
  jobState: string;
  archivedAt: string | null | undefined;
  actionLoading: boolean;
  resolveLoading: string | null;
  onCancelOpen: () => void;
  onResume: () => void;
  onResolve: (action: "merge" | "smart_merge" | "create_pr" | "agent_merge") => void;
  onDiscardOpen: () => void;
  onMarkDoneOpen: () => void;
  onCompleteOpen: () => void;
  /** Render compact (sidebar) vs full (mobile sheet) */
  layout?: "compact" | "full";
}

export function JobActions({
  canCancel,
  canResume,
  needsResolution,
  hasChanges,
  hasMergeConflict,
  isResolved,
  canArchive,
  jobState,
  archivedAt,
  actionLoading,
  resolveLoading,
  onCancelOpen,
  onResume,
  onResolve,
  onDiscardOpen,
  onMarkDoneOpen,
  onCompleteOpen,
  layout = "compact",
}: JobActionsProps) {
  const isCompact = layout === "compact";
  const btnSize = isCompact ? ("sm" as const) : ("sm" as const);
  const iconSize = isCompact ? 13 : 14;
  const btnClass = isCompact ? "h-7 text-xs" : "";

  const hasAny =
    canCancel || canResume || (needsResolution && hasChanges) ||
    (needsResolution && !hasChanges) || (isResolved && !archivedAt) || canArchive;

  if (!hasAny) return null;

  return (
    <div className={isCompact ? "flex flex-wrap gap-1.5" : "flex flex-wrap gap-2"}>
      {canCancel && (
        <Button size={btnSize} variant="outline" className={`${btnClass} text-destructive border-destructive/40 hover:bg-destructive/10`} onClick={onCancelOpen}>
          <XCircle size={iconSize} /> Cancel
        </Button>
      )}
      {canResume && (
        <Button size={btnSize} variant="outline" className={btnClass} loading={actionLoading} onClick={onResume}>
          <RotateCcw size={iconSize} /> Resume
        </Button>
      )}
      {needsResolution && hasChanges && (
        <>
          {!hasMergeConflict && (
            <Tooltip content="Merge changes onto the base branch">
              <Button size={btnSize} variant="outline" className={`${btnClass} gap-1`} loading={resolveLoading === "smart_merge"} disabled={resolveLoading !== null} onClick={() => onResolve("smart_merge")}>
                <GitMerge size={iconSize} /> Merge
              </Button>
            </Tooltip>
          )}
          {hasMergeConflict && (
            <Tooltip content="Resolve the merge conflict with the agent">
              <Button size={btnSize} variant="outline" className={`${btnClass} gap-1`} loading={resolveLoading === "agent_merge"} disabled={resolveLoading !== null} onClick={() => onResolve("agent_merge")}>
                <GitMerge size={iconSize} /> Resolve
              </Button>
            </Tooltip>
          )}
          <Button size={btnSize} variant="outline" className={`${btnClass} gap-1`} loading={resolveLoading === "create_pr"} disabled={resolveLoading !== null} onClick={() => onResolve("create_pr")}>
            <GitPullRequest size={iconSize} /> PR
          </Button>
          <Button size={btnSize} variant="outline" className={`${btnClass} gap-1 text-destructive border-destructive/40 hover:bg-destructive/10`} onClick={onDiscardOpen}>
            <Trash2 size={iconSize} />
          </Button>
        </>
      )}
      {needsResolution && !hasChanges && (
        <Button size={btnSize} variant="outline" className={`${btnClass} gap-1`} onClick={onMarkDoneOpen}>
          <CheckCircle2 size={iconSize} /> Done
        </Button>
      )}
      {isResolved && !archivedAt && (
        <Button size={btnSize} variant="outline" className={`${btnClass} gap-1 text-green-600 border-green-500/40 hover:bg-green-500/10`} onClick={onCompleteOpen}>
          <CheckCircle2 size={iconSize} /> Complete
        </Button>
      )}
      {canArchive && (
        <Button size={btnSize} variant="outline" className={`${btnClass} gap-1`} onClick={onCompleteOpen}>
          <Archive size={iconSize} /> {jobState === "failed" ? "Abandon" : "Archive"}
        </Button>
      )}
    </div>
  );
}
