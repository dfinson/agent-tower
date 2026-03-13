import { useCallback, useState } from "react";
import { useTowerStore, selectApprovals } from "../store";
import { resolveApproval } from "../api/client";
import { Button } from "../ui/Button";
import { toast } from "sonner";

export function ApprovalBanner({ jobId }: { jobId: string }) {
  const approvals = useTowerStore(selectApprovals);
  const [loading, setLoading] = useState<string | null>(null);

  const pending = Object.values(approvals).filter(
    (a) => a.jobId === jobId && !a.resolvedAt
  );

  const handleResolve = useCallback(async (approvalId: string, resolution: "approved" | "rejected") => {
    setLoading(approvalId);
    try {
      await resolveApproval(approvalId, resolution);
      toast.success(`Approval ${resolution}`);
    } catch (e) {
      toast.error(`Failed to ${resolution === "approved" ? "approve" : "reject"}: ${e}`);
    } finally {
      setLoading(null);
    }
  }, []);

  if (pending.length === 0) return null;

  return (
    <div className="space-y-2 mb-4">
      {pending.map((a) => (
        <div key={a.id} className="bg-warning/10 border border-warning rounded-lg p-4">
          <div className="flex justify-between items-start gap-4 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <div className="text-sm font-semibold text-yellow-400 mb-1">Approval Required</div>
              <div className="text-sm text-text">{a.description}</div>
              {a.proposedAction && (
                <div className="text-xs text-text-muted mt-1 font-mono">{a.proposedAction}</div>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={loading === a.id}
                onClick={() => handleResolve(a.id, "approved")}
              >
                Approve
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={loading === a.id}
                onClick={() => handleResolve(a.id, "rejected")}
              >
                Reject
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
