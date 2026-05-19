import { Radio, TerminalSquare, FolderTree, BarChart3, Package, ScanSearch } from "lucide-react";
import { Tooltip } from "./ui/tooltip";
import { cn } from "../lib/utils";

const TAB_ITEMS = [
  { id: "live", icon: Radio, label: "Live", tip: "Real-time agent activity feed" },
  { id: "files", icon: FolderTree, label: "Files", tip: "Browse the workspace file tree" },
  { id: "review", icon: ScanSearch, label: "Review", tip: "Review code changes and structural analysis", conditional: true },
  { id: "metrics", icon: BarChart3, label: "Metrics", tip: "Cost, tokens, and performance metrics" },
  { id: "artifacts", icon: Package, label: "Artifacts", tip: "Checkpoints, logs, and exported files", conditional: true },
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
}: ViewTabBarProps) {
  const visibleTabs = TAB_ITEMS.filter((t) => {
    if (t.id === "review") return hasChanges;
    if (t.id === "artifacts") return hasArtifacts;
    return true;
  });

  return (
    <div className="hidden md:flex items-center gap-0.5 mx-3 mt-1.5 px-3 h-9 rounded-lg border border-border bg-card shrink-0 overflow-x-auto scrollbar-none">
      {visibleTabs.map(({ id, icon: Icon, label, tip }) => (
        <Tooltip key={id} content={tip} side="bottom">
          <button
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
        </Tooltip>
      ))}
      {hasWorktree && (
        <>
          <div className="w-px h-4 bg-border mx-1" />
          <Tooltip content="Open a shell in the job's worktree" side="bottom">
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
          </Tooltip>
        </>
      )}
    </div>
  );
}
