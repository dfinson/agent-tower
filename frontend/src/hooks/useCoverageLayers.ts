/**
 * Hook: useCoverageLayers
 *
 * Fetches per-line coverage data for the active diff file and applies
 * Monaco glyph-margin decorations (green/red dots) on the modified editor.
 * Exposes click state so the parent can render a popover.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { fetchLineCoverage } from "../api/client";
import type { LineCoverageResponse, LineCoverageTestInfo } from "../api/types";

export interface CoveragePopoverState {
  visible: boolean;
  lineNumber: number;
  tests: LineCoverageTestInfo[];
  /** Pixel coordinates for positioning the popover */
  top: number;
  left: number;
}

interface GlyphDecorationLike {
  range: unknown;
  options: {
    glyphMarginClassName: string;
    glyphMarginHoverMessage: { value: string };
  };
}

interface CoverageMouseEventLike {
  target: {
    type: number;
    position?: {
      lineNumber?: number;
    };
  };
}

interface DisposableLike {
  dispose(): void;
}

interface ModifiedEditorLike {
  deltaDecorations(oldDecorations: string[], newDecorations: GlyphDecorationLike[]): string[];
  onMouseDown(listener: (event: CoverageMouseEventLike) => void): DisposableLike;
  getDomNode(): { getBoundingClientRect(): { top: number; left: number } } | null;
  getScrollTop(): number;
  getTopForLineNumber(lineNumber: number): number;
}

interface DiffEditorLike {
  getModifiedEditor(): ModifiedEditorLike | null;
}

interface MonacoRangeCtorLike {
  new (startLineNumber: number, startColumn: number, endLineNumber: number, endColumn: number): unknown;
}

interface MonacoLike {
  Range: MonacoRangeCtorLike;
  editor: {
    MouseTargetType: {
      GUTTER_GLYPH_MARGIN: number;
    };
  };
}

interface UseCoverageLayersOpts {
  jobId: string;
  filePath: string | undefined;
  enabled: boolean;
  editorRef: React.MutableRefObject<DiffEditorLike | null>;
  monacoRef: React.MutableRefObject<MonacoLike | null>;
  editorReady: boolean;
}

export function useCoverageLayers({
  jobId,
  filePath,
  enabled,
  editorRef,
  monacoRef,
  editorReady,
}: UseCoverageLayersOpts) {
  const [coverage, setCoverage] = useState<LineCoverageResponse | null>(null);
  const [popover, setPopover] = useState<CoveragePopoverState>({ visible: false, lineNumber: 0, tests: [], top: 0, left: 0 });
  const decorationIdsRef = useRef<string[]>([]);
  const disposableRef = useRef<DisposableLike | null>(null);

  // Fetch coverage when file changes (always fetch, toggle only controls display)
  useEffect(() => {
    if (!filePath) {
      setCoverage(null);
      return;
    }
    let cancelled = false;
    fetchLineCoverage(jobId, filePath)
      .then((res) => {
        if (!cancelled && res.available) setCoverage(res);
        else if (!cancelled) setCoverage(null);
      })
      .catch(() => { if (!cancelled) setCoverage(null); });
    return () => { cancelled = true; };
  }, [jobId, filePath]);

  // Apply decorations to modified editor
  useEffect(() => {
    const editor = editorRef.current;
    const m = monacoRef.current;
    if (!editor || !m || !editorReady) {
      return;
    }
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    if (!enabled || !coverage) {
      decorationIdsRef.current = modifiedEditor.deltaDecorations(decorationIdsRef.current, []);
      return;
    }

    const applyDecorations = () => {
      const ed = editorRef.current?.getModifiedEditor();
      if (!ed) return;
      const newDecorations: GlyphDecorationLike[] = [];

      for (const lineNo of coverage.coveredLines) {
        newDecorations.push({
          range: new m.Range(lineNo, 1, lineNo, 1),
          options: {
            glyphMarginClassName: "cov-dot-covered",
            glyphMarginHoverMessage: {
              value: `Covered by ${(coverage.testsByLine[String(lineNo)] || []).length || "≥1"} test(s)`,
            },
          },
        });
      }

      for (const lineNo of coverage.uncoveredLines) {
        newDecorations.push({
          range: new m.Range(lineNo, 1, lineNo, 1),
          options: {
            glyphMarginClassName: "cov-dot-uncovered",
            glyphMarginHoverMessage: { value: "Not covered by tests" },
          },
        });
      }

      decorationIdsRef.current = ed.deltaDecorations(decorationIdsRef.current, newDecorations);
    };

    applyDecorations();
    const timer = setTimeout(applyDecorations, 150);
    return () => clearTimeout(timer);
  }, [coverage, enabled, editorReady, editorRef, monacoRef]);

  // Handle glyph margin clicks for coverage dots
  useEffect(() => {
    const editor = editorRef.current;
    const m = monacoRef.current;
    if (!editor || !m || !editorReady || !enabled || !coverage) {
      disposableRef.current?.dispose();
      disposableRef.current = null;
      return;
    }
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    // Dispose previous listener
    disposableRef.current?.dispose();

    disposableRef.current = modifiedEditor.onMouseDown((e: CoverageMouseEventLike) => {
      if (e.target.type !== m.editor.MouseTargetType.GUTTER_GLYPH_MARGIN) return;
      const lineNumber = e.target.position?.lineNumber;
      if (lineNumber == null) return;

      // Only open popover for covered lines (which have tests)
      const tests = coverage.testsByLine[String(lineNumber)];
      if (!tests || tests.length === 0) return;

      // Get position for popover
      const editorDom = modifiedEditor.getDomNode();
      const scrollTop = modifiedEditor.getScrollTop();
      const lineTop = modifiedEditor.getTopForLineNumber(lineNumber) - scrollTop;
      const editorRect = editorDom?.getBoundingClientRect();
      const top = (editorRect?.top ?? 0) + lineTop + 18;
      const left = (editorRect?.left ?? 0) + 60;

      setPopover({ visible: true, lineNumber, tests, top, left });
    });

    return () => {
      disposableRef.current?.dispose();
      disposableRef.current = null;
    };
  }, [coverage, enabled, editorReady, editorRef, monacoRef]);

  const dismissPopover = useCallback(() => {
    setPopover((p) => ({ ...p, visible: false }));
  }, []);

  return { coverage, popover, dismissPopover };
}
