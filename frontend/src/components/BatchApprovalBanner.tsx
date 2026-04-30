import { useCallback, useState } from "react";
import { ShieldAlert, Check, X, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { useStore, selectBatchApprovals } from "../store";
import { resolveBatch } from "../api/client";
import { Button } from "./ui/button";
import { ConfirmDialog } from "./ui/confirm-dialog";

const TIER_ICON: Record<string, string> = {
  observe: "○",
  checkpoint: "◐",
  gate: "●",
};

export function BatchApprovalBanner({ jobId }: { jobId: string }) {
  const batchApprovals = useStore(selectBatchApprovals);
  const [loading, setLoading] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<string | null>(null);

  const pending = Object.values(batchApprovals).filter(
    (b) => b.jobId === jobId && !b.resolvedAt,
  );

  const handleResolve = useCallback(
    async (batchId: string, resolution: "approved" | "rejected" | "rollback") => {
      setLoading(batchId);
      try {
        await resolveBatch(jobId, batchId, resolution);
        toast.success(`Batch ${resolution}`);
      } catch (e) {
        toast.error(String(e));
      } finally {
        setLoading(null);
      }
    },
    [jobId],
  );

  if (pending.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {pending.map((batch) => (
        <div
          key={batch.batchId}
          className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <ShieldAlert size={16} className="text-amber-400 shrink-0" />
            <span className="text-sm font-semibold text-amber-300">
              Batch Approval — {batch.actions.length} action{batch.actions.length !== 1 ? "s" : ""}
            </span>
          </div>
          <p className="text-sm text-foreground mb-3">{batch.summary}</p>

          <div className="space-y-1.5 mb-3">
            {batch.actions.map((action) => (
              <div
                key={action.id}
                className="flex items-start gap-2 text-xs bg-background/50 border border-border/50 rounded px-2.5 py-1.5"
              >
                <span className="text-amber-400 font-mono shrink-0" title={`Tier: ${action.tier}`}>
                  {TIER_ICON[action.tier] ?? "●"}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="font-medium text-foreground">{action.description}</span>
                  <div className="flex gap-2 mt-0.5 text-muted-foreground">
                    <span>{action.kind}</span>
                    {!action.reversible && <span className="text-red-400">irreversible</span>}
                    {!action.contained && <span className="text-orange-400">uncontained</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex gap-2 w-full sm:w-auto">
            <Button
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white flex-1 sm:flex-none min-h-[44px] sm:min-h-0 gap-1"
              loading={loading === batch.batchId}
              onClick={() => handleResolve(batch.batchId, "approved")}
            >
              <Check size={14} />
              Approve All
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-red-500/40 text-red-400 hover:bg-red-500/10 flex-1 sm:flex-none min-h-[44px] sm:min-h-0 gap-1"
              loading={loading === batch.batchId}
              onClick={() => handleResolve(batch.batchId, "rejected")}
            >
              <X size={14} />
              Reject
            </Button>
            {batch.actions.some((a) => a.checkpointRef) && (
              <Button
                size="sm"
                variant="outline"
                className="border-amber-500/40 text-amber-400 hover:bg-amber-500/10 flex-1 sm:flex-none min-h-[44px] sm:min-h-0 gap-1"
                loading={loading === batch.batchId}
                onClick={() => setRollbackTarget(batch.batchId)}
              >
                <RotateCcw size={14} />
                Rollback
              </Button>
            )}
          </div>
        </div>
      ))}
      <ConfirmDialog
        open={!!rollbackTarget}
        onClose={() => setRollbackTarget(null)}
        onConfirm={async () => {
          if (rollbackTarget) await handleResolve(rollbackTarget, "rollback");
          setRollbackTarget(null);
        }}
        title="Rollback to Checkpoint?"
        description="This will revert changes made since the last checkpoint. The agent will continue from the reverted state."
        confirmLabel="Rollback"
      />
    </div>
  );
}
