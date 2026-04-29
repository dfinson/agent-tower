/**
 * Approval SSE event handlers.
 */

import type { ApprovalRequest } from "../types";
import type { SSEHandler, AppState } from "./types";

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export function handleApprovalRequested(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const approval: ApprovalRequest = {
    id: payload.approvalId as string,
    jobId: payload.jobId as string,
    description: payload.description as string,
    proposedAction: (payload.proposedAction as string | null) ?? null,
    requestedAt: (payload.timestamp as string) ?? new Date().toISOString(),
    resolvedAt: null,
    resolution: null,
    requiresExplicitApproval: (payload.requiresExplicitApproval as boolean) ?? false,
  };
  return {
    approvals: { ...state.approvals, [approval.id]: approval },
  };
}

export function handleApprovalResolved(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const approvalId = payload.approvalId as string;
  const existing = state.approvals[approvalId];
  if (existing) {
    return {
      approvals: {
        ...state.approvals,
        [approvalId]: {
          ...existing,
          resolution: payload.resolution as string,
          resolvedAt: payload.timestamp as string,
        },
      },
    };
  }
  return null;
}

export const approvalHandlers: Record<string, SSEHandler> = {
  approval_requested: handleApprovalRequested,
  approval_resolved: handleApprovalResolved,
};
