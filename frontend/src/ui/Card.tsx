import { cn } from "./cn";
import type { HTMLAttributes } from "react";

export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-lg border border-border bg-surface", className)} {...props}>
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("flex items-center justify-between px-4 py-3 border-b border-border", className)} {...props}>
      {children}
    </div>
  );
}

export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn("text-sm font-semibold text-text-muted", className)} {...props}>
      {children}
    </h3>
  );
}

export function CardContent({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("p-4", className)} {...props}>
      {children}
    </div>
  );
}

export function CardCount({ count, className }: { count: number; className?: string }) {
  return (
    <span className={cn("bg-surface-hover px-2 py-0.5 rounded-full text-xs text-text-muted", className)}>
      {count}
    </span>
  );
}
