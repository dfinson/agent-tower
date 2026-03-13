import { Badge } from "../ui/Badge";

export function StateBadge({ state }: { state: string }) {
  return <Badge state={state} />;
}
