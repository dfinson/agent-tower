import { useState } from "react";
import { ChevronRight } from "lucide-react";

// ---------------------------------------------------------------------------
// Collapsible section wrapper
// ---------------------------------------------------------------------------

export function CollapsibleSection({
  title,
  icon: Icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon?: React.ElementType;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-accent/30 transition-colors"
      >
        <h2 className="text-sm font-medium text-foreground flex items-center gap-2">
          {Icon && <Icon size={14} />}
          {title}
        </h2>
        <ChevronRight
          size={16}
          className={`text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4 min-w-0 overflow-x-auto">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton placeholder for loading sections
// ---------------------------------------------------------------------------

export function SectionSkeleton({ height = "h-40" }: { height?: string }) {
  return (
    <div className={`rounded-lg border border-border bg-card p-4 ${height} animate-pulse`}>
      <div className="h-3 w-24 bg-muted rounded mb-3" />
      <div className="h-6 w-16 bg-muted rounded mb-2" />
      <div className="space-y-2">
        <div className="h-2 w-full bg-muted rounded" />
        <div className="h-2 w-3/4 bg-muted rounded" />
      </div>
    </div>
  );
}
