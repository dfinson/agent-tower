import { useCallback, useEffect, useRef } from "react";

interface UseDragOptions {
  axis: "x" | "y";
  onDrag: (delta: number) => void;
  onDragEnd?: () => void;
}

export function useDrag({ axis, onDrag, onDragEnd }: UseDragOptions) {
  const dragging = useRef(false);
  const startPos = useRef(0);
  // Keep latest callbacks in refs to avoid stale closures in event handlers
  const onDragRef = useRef(onDrag);
  onDragRef.current = onDrag;
  const onDragEndRef = useRef(onDragEnd);
  onDragEndRef.current = onDragEnd;
  const cleanupRef = useRef<(() => void) | null>(null);

  // Clean up document listeners when component unmounts (prevents leak
  // if user navigates away mid-drag before mouseup/touchend fires).
  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, []);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startPos.current = axis === "y" ? e.clientY : e.clientX;

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const currentPos = axis === "y" ? ev.clientY : ev.clientX;
        onDragRef.current(startPos.current - currentPos);
      };

      const onUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        cleanupRef.current = null;
        onDragEndRef.current?.();
      };

      // Store cleanup so useEffect teardown can call it if component unmounts mid-drag
      cleanupRef.current = onUp;

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [axis],
  );

  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      dragging.current = true;
      const touch = e.touches[0];
      if (!touch) return;
      startPos.current = axis === "y" ? touch.clientY : touch.clientX;

      const onMove = (ev: TouchEvent) => {
        if (!dragging.current) return;
        const t = ev.touches[0];
        if (!t) return;
        const currentPos = axis === "y" ? t.clientY : t.clientX;
        onDragRef.current(startPos.current - currentPos);
      };

      const onEnd = () => {
        dragging.current = false;
        document.removeEventListener("touchmove", onMove);
        document.removeEventListener("touchend", onEnd);
        cleanupRef.current = null;
        onDragEndRef.current?.();
      };

      cleanupRef.current = onEnd;

      document.addEventListener("touchmove", onMove);
      document.addEventListener("touchend", onEnd);
    },
    [axis],
  );

  return { onMouseDown, onTouchStart };
}
