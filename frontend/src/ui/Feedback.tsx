import { cn } from "./cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-hover", className)} />;
}

export function EmptyState({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-12 text-text-dim text-sm", className)}>
      {text}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center justify-center py-8", className)}>
      <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
    </div>
  );
}
