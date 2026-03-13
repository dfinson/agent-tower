import { useState, useEffect, useCallback, type ReactNode } from "react";
import { useTowerStore, selectApprovals } from "../store";
import type { ApprovalRequest } from "../store";
import { resolveApproval } from "../api/client";

const AGING_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

function isAging(requestedAt: string): boolean {
  return Date.now() - new Date(requestedAt).getTime() > AGING_THRESHOLD_MS;
}

function AgingBadge({ requestedAt }: { requestedAt: string }): ReactNode {
  const [aging, setAging] = useState(() => isAging(requestedAt));

  useEffect(() => {
    if (aging) return;
    const remaining = AGING_THRESHOLD_MS - (Date.now() - new Date(requestedAt).getTime());
    if (remaining <= 0) {
      setAging(true);
      return;
    }
    const timer = setTimeout(() => setAging(true), remaining);
    return () => clearTimeout(timer);
  }, [requestedAt, aging]);

  if (!aging) return null;
  return <span className="badge badge--warning">Aging</span>;
}

export function ApprovalBanner({ jobId }: { jobId: string }): ReactNode {
  const approvals = useTowerStore(selectApprovals);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const pending = Object.values(approvals)
    .filter(
      (a: ApprovalRequest) =>
        a.jobId === jobId && a.resolution === null,
    )
    .sort(
      (a, b) =>
        new Date(a.requestedAt).getTime() - new Date(b.requestedAt).getTime(),
    );

  const handleResolve = useCallback(
    async (approvalId: string, resolution: "approved" | "rejected") => {
      setActionLoading(approvalId);
      try {
        const updated = await resolveApproval(approvalId, resolution);
        useTowerStore.setState((state) => ({
          approvals: { ...state.approvals, [updated.id]: updated },
        }));
      } catch {
        // ApiError already thrown
      } finally {
        setActionLoading(null);
      }
    },
    [],
  );

  if (pending.length === 0) return null;

  return (
    <div className="approval-banner">
      {pending.map((approval) => (
        <div key={approval.id} className="approval-banner__item">
          <div className="approval-banner__header">
            <span className="approval-banner__title">
              Approval Required
            </span>
            <AgingBadge requestedAt={approval.requestedAt} />
          </div>
          <p className="approval-banner__description">
            {approval.description}
          </p>
          {approval.proposedAction && (
            <pre className="approval-banner__action">
              {approval.proposedAction}
            </pre>
          )}
          <div className="approval-banner__buttons">
            <button
              className="btn btn--sm btn--success"
              disabled={actionLoading === approval.id}
              onClick={() => handleResolve(approval.id, "approved")}
            >
              Approve
            </button>
            <button
              className="btn btn--sm btn--danger"
              disabled={actionLoading === approval.id}
              onClick={() => handleResolve(approval.id, "rejected")}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
