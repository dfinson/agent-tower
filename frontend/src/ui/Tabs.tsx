import { cn } from "./cn";

interface TabsProps {
  tabs: { id: string; label: string; badge?: number }[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className }: TabsProps) {
  return (
    <div className={cn("flex gap-1 border-b border-border", className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={cn(
            "relative px-3 py-2 text-sm font-medium transition-colors rounded-t-md",
            active === tab.id
              ? "text-text bg-surface border-b-2 border-accent"
              : "text-text-muted hover:text-text hover:bg-surface-hover"
          )}
        >
          {tab.label}
          {tab.badge != null && tab.badge > 0 && (
            <span className="absolute -top-1 -right-1 bg-error text-white text-[10px] px-1.5 rounded-full min-w-[16px] text-center">
              {tab.badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
