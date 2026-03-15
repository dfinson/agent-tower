import { useCallback, useState } from "react";
import { ShieldQuestion } from "lucide-react";
import { toast } from "sonner";
import { useTowerStore, selectApprovals } from "../store";
import { resolveApproval } from "../api/client";
import { Button } from "./ui/button";

export function ApprovalBanner({ jobId }: { jobId: string }) {
  const approvals = useTowerStore(selectApprovals);
  const [loading, setLoading] = useState<string | null>(null);

  const pending = Object.values(approvals).filter(
    (a) => a.jobId === jobId && !a.resolvedAt,
  );

  const handleResolve = useCallback(
    async (approvalId: string, resolution: "approved" | "rejected") => {
      setLoading(approvalId);
      try {
        await resolveApproval(approvalId, resolution);
        toast.success(`Approval ${resolution}`);
      } catch (e) {
        toast.error(String(e));
      } finally {
        setLoading(null);
      }
    },
    [],
  );

  if (pending.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {pending.map((a) => (
        <div
          key={a.id}
          className="rounded-lg border border-orange-500/40 bg-orange-500/10 p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <ShieldQuestion size={16} className="text-orange-400 shrink-0" />
            <span className="text-sm font-semibold text-orange-300">Approval Required</span>
          </div>
          <p className="text-sm text-foreground mb-2">{a.description}</p>
          {a.proposedAction && (
            <pre className="text-xs bg-background border border-border rounded p-2 mb-3 overflow-x-auto font-mono">
              {a.proposedAction}
            </pre>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white"
              loading={loading === a.id}
              onClick={() => handleResolve(a.id, "approved")}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-red-500/40 text-red-400 hover:bg-red-500/10"
              loading={loading === a.id}
              onClick={() => handleResolve(a.id, "rejected")}
            >
              Reject
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
