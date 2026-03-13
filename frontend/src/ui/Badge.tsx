import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "./cn";
import type { ReactNode } from "react";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "bg-surface text-text-muted",
        running: "bg-accent/20 text-accent",
        queued: "bg-warning/20 text-warning",
        waiting_for_approval: "bg-warning/25 text-yellow-400",
        succeeded: "bg-success/20 text-success",
        failed: "bg-error/20 text-error",
        canceled: "bg-surface text-text-dim",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

const STATE_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  waiting_for_approval: "Approval",
  succeeded: "Succeeded",
  failed: "Failed",
  canceled: "Canceled",
};

interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children?: ReactNode;
  state?: string;
  className?: string;
}

export function Badge({ variant, state, children, className }: BadgeProps) {
  const resolvedVariant = (state ?? variant ?? "default") as BadgeProps["variant"];
  const label = children ?? (state ? STATE_LABELS[state] ?? state : "");
  return <span className={cn(badgeVariants({ variant: resolvedVariant }), className)}>{label}</span>;
}
