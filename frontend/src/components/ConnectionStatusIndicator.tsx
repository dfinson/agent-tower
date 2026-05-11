import { useStore, selectConnectionStatus } from "../store";
import { DotBadge } from "./ui/badge";
import { Tooltip } from "./ui/tooltip";

export function ConnectionStatusIndicator() {
  const status = useStore(selectConnectionStatus);
  const color = status === "connected" ? "green" : status === "disconnected" ? "red" : "yellow";
  const label =
    status === "connecting" ? "Connecting\u2026"
    : status === "reconnecting" ? "Reconnecting\u2026"
    : status === "connected" ? "Connected"
    : "Disconnected";
  const tip =
    status === "connected" ? "Live event stream is active — updates arrive in real time"
    : status === "connecting" ? "Establishing the live event stream…"
    : status === "reconnecting" ? "Connection lost — attempting to reconnect…"
    : "Live event stream is down — updates may be stale";
  return (
    <Tooltip content={tip}>
      <DotBadge color={color} aria-live="polite" aria-label={`Connection status: ${label}`}>
        {label}
      </DotBadge>
    </Tooltip>
  );
}
