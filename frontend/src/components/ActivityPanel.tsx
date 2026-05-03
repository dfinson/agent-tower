import { useState, useCallback, useRef, useEffect } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { ActivityTimeline } from "./ActivityTimeline";
import { Tooltip } from "./ui/tooltip";
import { cn } from "../lib/utils";

interface ActivityPanelProps {
  jobId: string;
  jobState: string;
  selectedTurnId: string | null;
  searchActive: boolean;
  visibleStepTurnId: string | null;
  onStepClick: (turnId: string) => void;
}

export function ActivityPanel({
  jobId,
  jobState,
  selectedTurnId,
  searchActive,
  visibleStepTurnId,
  onStepClick,
}: ActivityPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [width, setWidth] = useState(() => Math.max(200, Math.min(320, window.innerWidth * 0.15)));
  const isResizingRef = useRef(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => () => { cleanupRef.current?.(); }, []);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizingRef.current = true;
    const startX = e.clientX;
    const startWidth = width;
    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizingRef.current) return;
      const delta = ev.clientX - startX;
      setWidth(Math.max(140, Math.min(400, startWidth + delta)));
    };
    const onMouseUp = () => {
      isResizingRef.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      cleanupRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    cleanupRef.current = onMouseUp;
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [width]);

  return (
    <>
      <div
        className={cn(
          "hidden md:flex flex-col flex-shrink-0 md:h-full rounded-lg border border-border bg-card overflow-hidden",
          collapsed && "w-10",
        )}
        style={collapsed ? undefined : { width }}
      >
        {collapsed ? (
          <Tooltip content="Show activity">
            <button
              onClick={() => setCollapsed(false)}
              className="flex items-center justify-center h-full text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
            >
              <PanelLeftOpen size={18} />
            </button>
          </Tooltip>
        ) : (
          <>
            <button
              onClick={() => setCollapsed(true)}
              className="flex items-center gap-2 px-3 py-1.5 w-full text-left hover:bg-accent/50 transition-colors shrink-0 border-b border-border"
              title="Collapse activity"
            >
              <PanelLeftClose size={13} className="text-muted-foreground shrink-0" />
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">Activity</span>
            </button>
            <div className="flex-1 overflow-hidden">
              <ActivityTimeline
                jobId={jobId}
                jobState={jobState}
                onStepClick={onStepClick}
                selectedTurnId={selectedTurnId}
                searchActive={searchActive}
                visibleStepTurnId={visibleStepTurnId}
              />
            </div>
          </>
        )}
      </div>
      {/* Drag handle for resizing */}
      {!collapsed && (
        <div
          className="hidden md:flex items-center justify-center w-2 cursor-col-resize group flex-shrink-0"
          onMouseDown={handleResizeStart}
          title="Drag to resize"
        >
          <div className="w-0.5 h-8 rounded-full bg-border group-hover:bg-muted-foreground/60 transition-colors" />
        </div>
      )}
    </>
  );
}
