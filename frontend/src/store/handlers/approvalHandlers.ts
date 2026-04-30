/**
 * Approval SSE event handlers.
 */

import type { ApprovalRequest, BatchApproval } from "../types";
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

export function handleBatchApprovalRequested(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const actions = (payload.actions as Array<Record<string, unknown>>) ?? [];
  const batch: BatchApproval = {
    batchId: payload.batch_id as string,
    jobId: payload.jobId as string,
    actions: actions.map((a) => ({
      id: a.id as string,
      kind: a.kind as string,
      tier: a.tier as string,
      reason: a.reason as string,
      reversible: a.reversible as boolean,
      contained: a.contained as boolean,
      checkpointRef: (a.checkpoint_ref as string | null) ?? null,
      description: a.description as string,
    })),
    summary: (payload.summary as string) ?? "",
    requestedAt: (payload.timestamp as string) ?? new Date().toISOString(),
    resolvedAt: null,
    resolution: null,
  };
  return {
    batchApprovals: { ...state.batchApprovals, [batch.batchId]: batch },
  };
}

export function handleBatchApprovalResolved(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const batchId = payload.batch_id as string;
  const existing = state.batchApprovals[batchId];
  if (existing) {
    return {
      batchApprovals: {
        ...state.batchApprovals,
        [batchId]: {
          ...existing,
          resolution: payload.resolution as string,
          resolvedAt: (payload.timestamp as string) ?? new Date().toISOString(),
        },
      },
    };
  }
  return null;
}

export const approvalHandlers: Record<string, SSEHandler> = {
  approval_requested: handleApprovalRequested,
  approval_resolved: handleApprovalResolved,
  batch_approval_requested: handleBatchApprovalRequested,
  batch_approval_resolved: handleBatchApprovalResolved,
};
