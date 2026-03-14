import { useCallback, useState } from "react";
import { Alert, Button, Group, Text, Code } from "@mantine/core";
import { ShieldQuestion } from "lucide-react";
import { useTowerStore, selectApprovals } from "../store";
import { resolveApproval } from "../api/client";
import { notifications } from "@mantine/notifications";

export function ApprovalBanner({ jobId }: { jobId: string }) {
  const approvals = useTowerStore(selectApprovals);
  const [loading, setLoading] = useState<string | null>(null);

  const pending = Object.values(approvals).filter(
    (a) => a.jobId === jobId && !a.resolvedAt
  );

  const handleResolve = useCallback(
    async (approvalId: string, resolution: "approved" | "rejected") => {
      setLoading(approvalId);
      try {
        await resolveApproval(approvalId, resolution);
        notifications.show({ color: "green", message: `Approval ${resolution}` });
      } catch (e) {
        notifications.show({ color: "red", title: "Failed", message: String(e) });
      } finally {
        setLoading(null);
      }
    },
    []
  );

  if (pending.length === 0) return null;

  return (
    <div className="space-y-2">
      {pending.map((a) => (
        <Alert key={a.id} color="orange" icon={<ShieldQuestion size={18} />} title="Approval Required" radius="lg">
          <Text size="sm" mb="xs">{a.description}</Text>
          {a.proposedAction && <Code block mb="sm">{a.proposedAction}</Code>}
          <Group gap="xs">
            <Button
              size="xs"
              color="green"
              loading={loading === a.id}
              onClick={() => handleResolve(a.id, "approved")}
            >
              Approve
            </Button>
            <Button
              size="xs"
              color="red"
              variant="outline"
              loading={loading === a.id}
              onClick={() => handleResolve(a.id, "rejected")}
            >
              Reject
            </Button>
          </Group>
        </Alert>
      ))}
    </div>
  );
}
