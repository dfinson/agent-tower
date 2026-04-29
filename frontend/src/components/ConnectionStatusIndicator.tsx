import { useStore, selectConnectionStatus } from "../store";
import { DotBadge } from "./ui/badge";

export function ConnectionStatusIndicator() {
  const status = useStore(selectConnectionStatus);
  const color = status === "connected" ? "green" : status === "disconnected" ? "red" : "yellow";
  const label =
    status === "connecting" ? "Connecting\u2026"
    : status === "reconnecting" ? "Reconnecting\u2026"
    : status === "connected" ? "Connected"
    : "Disconnected";
  return (
    <DotBadge color={color} aria-live="polite" aria-label={`Connection status: ${label}`}>
      {label}
    </DotBadge>
  );
}
