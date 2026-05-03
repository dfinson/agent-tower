import { Radio, TerminalSquare, FolderTree, GitBranch, BarChart3, Package } from "lucide-react";
import { cn } from "../lib/utils";

const TAB_ITEMS = [
  { id: "live", icon: Radio, label: "Live" },
  { id: "files", icon: FolderTree, label: "Files" },
  { id: "diff", icon: GitBranch, label: "Changes", conditional: true },
  { id: "metrics", icon: BarChart3, label: "Metrics" },
  { id: "artifacts", icon: Package, label: "Artifacts", conditional: true },
] as const;

interface ViewTabBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  hasChanges: boolean;
  hasArtifacts: boolean;
  artifactCount: number;
  hasWorktree: boolean;
  jobTerminalCount: number;
  onOpenTerminal: () => void;
  isRunning: boolean;
  onOpenAgentTerminal: () => void;
}

export function ViewTabBar({
  activeTab,
  onTabChange,
  hasChanges,
  hasArtifacts,
  artifactCount,
  hasWorktree,
  jobTerminalCount,
  onOpenTerminal,
  isRunning,
  onOpenAgentTerminal,
}: ViewTabBarProps) {
  const visibleTabs = TAB_ITEMS.filter((t) => {
    if (t.id === "diff") return hasChanges;
    if (t.id === "artifacts") return hasArtifacts;
    return true;
  });

  return (
    <div className="hidden md:flex items-center gap-0.5 mx-3 mt-1.5 px-3 h-9 rounded-lg border border-border bg-card shrink-0 overflow-x-auto scrollbar-none">
      {visibleTabs.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          onClick={() => onTabChange(id)}
          className={cn(
            "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap relative",
            activeTab === id
              ? "text-primary"
              : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
          )}
        >
          <Icon size={14} className="shrink-0" />
          <span>{label}</span>
          {id === "artifacts" && artifactCount > 0 && (
            <span className="text-[9px] leading-none bg-muted text-muted-foreground rounded-full px-1 py-0.5 font-normal">
              {artifactCount}
            </span>
          )}
          {activeTab === id && (
            <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
          )}
        </button>
      ))}
      {hasWorktree && (
        <>
          <div className="w-px h-4 bg-border mx-1" />
          <button
            onClick={onOpenTerminal}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors whitespace-nowrap"
          >
            <TerminalSquare size={14} className="shrink-0" />
            <span>Terminal</span>
            {jobTerminalCount > 0 && (
              <span className="text-[9px] font-bold text-primary">{jobTerminalCount}</span>
            )}
          </button>
        </>
      )}
      {isRunning && (
        <>
          {!hasWorktree && <div className="w-px h-4 bg-border mx-1" />}
          <button
            onClick={onOpenAgentTerminal}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors whitespace-nowrap"
          >
            <Radio size={14} className="shrink-0 text-green-500 animate-pulse" />
            <span>Agent</span>
          </button>
        </>
      )}
    </div>
  );
}
