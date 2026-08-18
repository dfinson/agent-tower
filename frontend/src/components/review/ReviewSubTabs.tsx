/**
 * Sub-tab bar for the Review tab — switches between Changes and Story.
 */
import { BookOpen, GitBranch } from "lucide-react";
import { ViewTabBar } from "../ViewTabBar";

export type ReviewSubView = "changes" | "story";

interface ReviewSubTabsProps {
  active: ReviewSubView;
  onChange: (view: ReviewSubView) => void;
  showChanges?: boolean;
}

export function ReviewSubTabs({ active, onChange, showChanges = true }: ReviewSubTabsProps) {
  return (
    <ViewTabBar
      activeTab={active}
      onTabChange={(view) => onChange(view as ReviewSubView)}
      items={[
        { id: "changes", icon: GitBranch, label: "Changes", hidden: !showChanges },
        { id: "story", icon: BookOpen, label: "Story" },
      ]}
      variant="inline"
      mobileBehavior="visible"
      className="gap-0 px-4 pt-3"
      itemClassName="py-1.5 text-xs"
    />
  );
}
