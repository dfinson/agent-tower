import type { ReactNode } from "react";

const STATE_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  waiting_for_approval: "Approval",
  succeeded: "Succeeded",
  failed: "Failed",
  canceled: "Canceled",
};

export function StateBadge({ state }: { state: string }): ReactNode {
  const label = STATE_LABELS[state] ?? state;
  return <span className={`badge badge--${state}`}>{label}</span>;
}
