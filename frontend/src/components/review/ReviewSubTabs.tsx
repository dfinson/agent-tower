/**
 * Sub-tab bar for the Review tab — switches between Changes and Story.
 */
import { BookOpen, GitBranch } from "lucide-react";

export type ReviewSubView = "changes" | "story";

interface ReviewSubTabsProps {
  active: ReviewSubView;
  onChange: (view: ReviewSubView) => void;
  showChanges?: boolean;
}

const TABS: Array<{ id: ReviewSubView; icon: typeof GitBranch; label: string }> = [
  { id: "changes", icon: GitBranch, label: "Changes" },
  { id: "story", icon: BookOpen, label: "Story" },
];

export function ReviewSubTabs({ active, onChange, showChanges = true }: ReviewSubTabsProps) {
  return (
    <div className="flex items-center gap-1 px-4 pt-3 pb-1">
      {TABS.map(({ id, icon: Icon, label }) => {
        if (id === "changes" && !showChanges) return null;
        const isActive = active === id;
        return (
          <button
            key={id}
            onClick={() => onChange(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              isActive
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
            }`}
          >
            <Icon size={13} />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
