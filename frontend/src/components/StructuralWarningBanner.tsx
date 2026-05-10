/**
 * Banner showing structural warnings accumulated during job execution (§7.2).
 * Renders inline below the activity panel when the agent is running.
 */
import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, RefreshCcw, GitFork } from "lucide-react";
import { useStore } from "../store";

interface StructuralWarningBannerProps {
  jobId: string;
}

const WARNING_ICONS: Record<string, typeof AlertTriangle> = {
  new_cycles: RefreshCcw,
  community_drift: GitFork,
};

export function StructuralWarningBanner({ jobId }: StructuralWarningBannerProps) {
  const warnings = useStore((s) => s.structuralWarnings[jobId]);
  const [expanded, setExpanded] = useState(false);

  if (!warnings || warnings.length === 0) return null;

  const latest = warnings[warnings.length - 1]!;
  const Icon = WARNING_ICONS[latest.warningType] ?? AlertTriangle;

  return (
    <div className="mx-4 mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5">
      <button
        className="flex items-center gap-2 px-3 py-2 w-full text-left"
        onClick={() => setExpanded((e) => !e)}
      >
        <Icon size={14} className="text-amber-400 shrink-0" />
        <span className="text-xs font-medium text-amber-400 flex-1">
          {warnings.length} structural warning{warnings.length !== 1 ? "s" : ""}
        </span>
        {expanded
          ? <ChevronDown size={12} className="text-muted-foreground" />
          : <ChevronRight size={12} className="text-muted-foreground" />}
      </button>
      {expanded && (
        <div className="px-3 pb-2 flex flex-col gap-1">
          {warnings.map((w, i) => {
            const WIcon = WARNING_ICONS[w.warningType] ?? AlertTriangle;
            return (
              <div key={i} className="flex items-start gap-2 text-xs text-foreground/80 pl-1">
                <WIcon size={12} className="text-amber-400/70 shrink-0 mt-0.5" />
                <span>{w.detail}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
