import { cn } from "../../lib/utils";

export function Progress({
  value,
  color = "blue",
  className,
}: {
  value: number;
  color?: "blue" | "red" | "green";
  className?: string;
}) {
  const track = { blue: "bg-primary", red: "bg-red-500", green: "bg-green-500" }[color];
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-secondary", className)}>
      <div
        className={cn("h-full transition-all", track)}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
