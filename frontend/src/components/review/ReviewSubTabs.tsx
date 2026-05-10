/**
 * Sub-tab bar for the Review tab — switches between Dashboard, Timeline, Communities, and Story.
 */
import { LayoutDashboard, Clock, BookOpen, Network, ScrollText } from "lucide-react";

export type ReviewSubView = "dashboard" | "timeline" | "communities" | "narrative" | "story";

interface ReviewSubTabsProps {
  active: ReviewSubView;
  onChange: (view: ReviewSubView) => void;
  showTimeline: boolean;
  showCommunities?: boolean;
}

const TABS: Array<{ id: ReviewSubView; icon: typeof LayoutDashboard; label: string }> = [
  { id: "dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { id: "timeline", icon: Clock, label: "Timeline" },
  { id: "communities", icon: Network, label: "Communities" },
  { id: "narrative", icon: ScrollText, label: "Narrative" },
  { id: "story", icon: BookOpen, label: "Story" },
];

export function ReviewSubTabs({ active, onChange, showTimeline, showCommunities = true }: ReviewSubTabsProps) {
  return (
    <div className="flex items-center gap-1 px-4 pt-3 pb-1">
      {TABS.map(({ id, icon: Icon, label }) => {
        if (id === "timeline" && !showTimeline) return null;
        if (id === "communities" && !showCommunities) return null;
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
