import { Badge } from "@mantine/core";
import {
  type LucideIcon,
  Loader2,
  Clock,
  ShieldQuestion,
  CheckCircle2,
  XCircle,
  Ban,
} from "lucide-react";

const STATE_CONFIG: Record<string, { color: string; label: string; icon: LucideIcon }> = {
  queued: { color: "yellow", label: "Queued", icon: Clock },
  running: { color: "blue", label: "Running", icon: Loader2 },
  waiting_for_approval: { color: "orange", label: "Approval", icon: ShieldQuestion },
  succeeded: { color: "green", label: "Succeeded", icon: CheckCircle2 },
  failed: { color: "red", label: "Failed", icon: XCircle },
  canceled: { color: "gray", label: "Canceled", icon: Ban },
};

export function StateBadge({ state }: { state: string }) {
  const cfg = STATE_CONFIG[state] ?? { color: "gray", label: state, icon: Clock };
  const Icon = cfg.icon;
  return (
    <Badge
      color={cfg.color}
      variant="light"
      size="sm"
      leftSection={<Icon size={12} />}
    >
      {cfg.label}
    </Badge>
  );
}
