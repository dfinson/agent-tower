/**
 * Hook: useImpactLayers
 *
 * Reads per-file symbol impact data embedded in DiffFileModel (populated by
 * CodeRecon semantic_diff on the backend) and injects Monaco view zones
 * showing collapsed/expandable impact panels below the relevant lines.
 *
 * No frontend heuristics — symbol resolution is fully deterministic via CodeRecon.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type { DiffFileModel } from "../api/types";
import { fetchImpactGraphBatch } from "../api/client";
import type { ImpactGraphResponse } from "../api/client";

/** Escape HTML special characters to prevent XSS when inserting into innerHTML. */
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export interface ImpactCaller {
  symbol: string;
  file: string;
  line: number | null;
  tier: string;
  isTest: boolean;
  covered: boolean | null;
  testPassed: boolean | null;
  coveringTestIds: string[];
  stale: boolean | null;
}

export interface ImpactZoneData {
  symbolName: string;
  afterLine: number;
  summary: string;
  totalReferences: number;
  callers: ImpactCaller[];
  expanded: boolean;
  category: string;
  failCount: number;
  uncoveredCount: number;
}

interface UseImpactLayersOpts {
  jobId: string;
  file: DiffFileModel | undefined;
  enabled: boolean;
  editorRef: React.MutableRefObject<any>;
  monacoRef: React.MutableRefObject<any>;
  editorReady: boolean;
}

export function useImpactLayers({
  jobId,
  file,
  enabled,
  editorRef,
  monacoRef,
  editorReady,
}: UseImpactLayersOpts) {
  const [zones, setZones] = useState<ImpactZoneData[]>([]);
  const viewZoneIdsRef = useRef<string[]>([]);
  const zoneDomsRef = useRef<Map<string, HTMLElement>>(new Map());
  const zoneIdMapRef = useRef<Map<string, string>>(new Map());
  const toggleZoneRef = useRef<(symbolName: string) => void>(() => {});

  const toggleZone = useCallback((symbolName: string) => {
    setZones((prev) =>
      prev.map((z) => (z.symbolName === symbolName ? { ...z, expanded: !z.expanded } : z)),
    );
  }, []);

  toggleZoneRef.current = toggleZone;

  // Fetch impact graph data for all symbols in a single batch request.
  // Uses file.symbols to know WHICH symbols to fetch,
  // then fetches full caller data from /impact-graph-batch.
  // Results are cached per file path to avoid refetching on re-render.
  const batchCacheRef = useRef<Map<string, Record<string, ImpactGraphResponse>>>(new Map());

  useEffect(() => {
    if (!file || !enabled) {
      setZones([]);
      return;
    }

    const symbols = file.symbols;
    if (!symbols || symbols.length === 0) {
      setZones([]);
      return;
    }

    const symbolsToFetch = symbols.filter((sym) => sym.refCount > 0);
    if (symbolsToFetch.length === 0) {
      setZones([]);
      return;
    }

    const filePath = file.path;
    let cancelled = false;

    async function fetchAll() {
      const symbolNames = symbolsToFetch.map((s) => s.symbol);

      // Check cache — invalidate when file changes
      const cached = batchCacheRef.current.get(filePath);
      let batchResults: Record<string, ImpactGraphResponse>;

      if (cached && symbolNames.every((s) => s in cached)) {
        batchResults = cached;
      } else {
        try {
          const resp = await fetchImpactGraphBatch(jobId, symbolNames);
          batchResults = resp.results;
          // Update cache for this file
          batchCacheRef.current.set(filePath, batchResults);
        } catch {
          // On batch failure, set all zones empty
          if (!cancelled) setZones([]);
          return;
        }
      }

      if (cancelled) return;

      const newZones: ImpactZoneData[] = [];
      for (const sym of symbolsToFetch) {
        const resp = batchResults[sym.symbol];
        if (!resp || !resp.available || resp.totalReferences === 0) continue;

        const callers: ImpactCaller[] = resp.references.map((ref) => ({
          symbol: ref.symbol,
          file: ref.file,
          line: ref.line,
          tier: ref.tier,
          isTest: ref.isTest,
          covered: ref.covered,
          testPassed: ref.testPassed,
          coveringTestIds: ref.coveringTestIds ?? [],
          stale: ref.stale,
        }));

        const summary = resp.summary || `${resp.totalReferences} reference(s)`;

        newZones.push({
          symbolName: sym.symbol,
          afterLine: sym.lineRange?.[1] ?? 1,
          summary,
          totalReferences: resp.totalReferences,
          callers,
          expanded: false,
          category: sym.category,
          failCount: resp.failCount ?? 0,
          uncoveredCount: resp.uncoveredCount ?? 0,
        });
      }

      setZones(newZones);
    }

    fetchAll();
    return () => { cancelled = true; };
  }, [file, enabled, jobId]);

  // Inject view zones into the modified editor
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !editorReady) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    modifiedEditor.changeViewZones((accessor: any) => {
      viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
      viewZoneIdsRef.current = [];
      zoneDomsRef.current.clear();

      if (!enabled || zones.length === 0) {
        zoneIdMapRef.current = new Map();
        return;
      }

      const model = modifiedEditor.getModel();
      const newIds: string[] = [];
      const newZoneIdMap = new Map<string, string>();

      for (const zone of zones) {
        // Resolve afterLine in MODIFIED content coordinates using the live model
        let afterLine = zone.afterLine;
        if (model) {
          const lineCount = model.getLineCount();
          const symbolPattern = new RegExp(
            `\\b(?:function|class|const|let|var|def|async\\s+function)\\s+${zone.symbolName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`,
          );
          for (let ln = 1; ln <= lineCount; ln++) {
            const lineContent = model.getLineContent(ln);
            if (symbolPattern.test(lineContent)) {
              let depth = 0;
              let foundOpen = false;
              for (let j = ln; j <= lineCount; j++) {
                const line = model.getLineContent(j);
                for (const ch of line) {
                  if (ch === "{") { depth++; foundOpen = true; }
                  else if (ch === "}") { depth--; }
                }
                if (foundOpen && depth <= 0) {
                  afterLine = j;
                  break;
                }
              }
              break;
            }
          }
          // Clamp to valid range
          afterLine = Math.min(afterLine, lineCount);
        }
        const domNode = document.createElement("div");
        domNode.className = "impact-zone-container";
        domNode.dataset.symbol = zone.symbolName;

        // Category determines badge style and summary text
        const isBreaking = zone.category === "breaking";
        const categoryClass = isBreaking ? "impact-badge-breaking" : "";
        const summaryText = (() => {
          const n = zone.totalReferences;
          const noun = n === 1 ? "caller" : "callers";
          if (isBreaking) return `${n} ${noun} affected by signature change`;
          if (zone.category === "body") return `${n} ${noun} affected by implementation change`;
          if (zone.category === "additive") return `${n} ${noun}`;
          return zone.summary;
        })();

        // Dot class: fail > uncovered > covered > isTest fallback
        function dotClass(c: ImpactCaller): string {
          if (c.testPassed === false) return "fail";
          if (c.covered === false) return "uncovered";
          if (c.covered === true) return "covered";
          return c.isTest ? "test" : "source";
        }

        // Callers list HTML
        const callersHtml = zone.callers.slice(0, 10).map((c) => `
          <div class="impact-caller-card">
            <span class="impact-caller-dot ${dotClass(c)}"></span>
            <span class="impact-caller-name">${escapeHtml(c.symbol || "(anonymous)")}</span>
            <span class="impact-caller-loc">${escapeHtml(c.file)}${c.line ? `:${c.line}` : ""}</span>
          </div>
        `).join("");
        const moreHtml = zone.callers.length > 10 ? `<div class="impact-more">+${zone.callers.length - 10} more</div>` : "";

        // Pills: fail count, then test count
        const failCount = zone.failCount;
        const testCount = zone.callers.filter((c) => c.isTest).length;
        const pillsHtml = [
          failCount > 0 ? `<span class="impact-fail-pill">${failCount} FAIL</span>` : "",
          testCount > 0 ? `<span class="impact-test-pill">${testCount} test${testCount > 1 ? "s" : ""}</span>` : "",
        ].filter(Boolean).join("");

        domNode.innerHTML = `
          <div class="impact-zone-header" data-symbol="${escapeHtml(zone.symbolName)}">
            <span class="impact-chevron">${zone.expanded ? "▼" : "▶"}</span>
            <span class="impact-badge ${categoryClass}">Impact</span>
            <span class="impact-summary">${escapeHtml(summaryText)}</span>
            ${pillsHtml}
          </div>
          <div class="impact-zone-body" style="display: ${zone.expanded ? "block" : "none"};">
            ${callersHtml}
            ${moreHtml}
          </div>
        `;

        zoneDomsRef.current.set(zone.symbolName, domNode);

        // Dynamic height: collapsed = 28px, expanded = header + callers
        const callerCount = Math.min(zone.callers.length, 10);
        const expandedHeight = 28 + (callerCount * 26) + (zone.callers.length > 10 ? 22 : 0);
        const heightInPx = zone.expanded ? expandedHeight : 28;

        const id = accessor.addZone({
          afterLineNumber: afterLine,
          heightInPx,
          domNode,
          suppressMouseDown: true,
        });
        newIds.push(id);
        newZoneIdMap.set(id, zone.symbolName);
      }
      viewZoneIdsRef.current = newIds;
      zoneIdMapRef.current = newZoneIdMap;
    });

    // Force relayout after DiffEditor's reactive recomputation settles.
    // The DiffEditor listens to onDidChangeViewZones and recomputes alignment
    // zones via RunOnceScheduler(0). Our zones get display:none until we force
    // a layoutZone pass after that settles.
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (viewZoneIdsRef.current.length > 0) {
      timer = setTimeout(() => {
        modifiedEditor.changeViewZones((accessor: any) => {
          for (const id of viewZoneIdsRef.current) {
            accessor.layoutZone(id);
          }
        });
      }, 0);
    }
    return () => { if (timer) clearTimeout(timer); };
  }, [zones, enabled, editorReady, editorRef, monacoRef]);

  // Register Monaco onMouseDown handler for view zone click detection.
  // With suppressMouseDown: true, Monaco uses coordinate-based hit-testing to
  // identify clicks in view zone whitespace and exposes them via the onMouseDown
  // API with target.type === CONTENT_VIEW_ZONE (includes viewZoneId in detail).
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !editorReady) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;
    const monaco = monacoRef.current;
    if (!monaco) return;

    const CONTENT_VIEW_ZONE = monaco.editor.MouseTargetType.CONTENT_VIEW_ZONE;

    const disposable = modifiedEditor.onMouseDown((e: any) => {
      if (e.target.type !== CONTENT_VIEW_ZONE) return;
      const viewZoneId = e.target.detail?.viewZoneId;
      if (!viewZoneId) return;
      const symbolName = zoneIdMapRef.current.get(viewZoneId);
      if (!symbolName) return; // not our zone (could be diff editor filler)
      toggleZoneRef.current(symbolName);
    });

    return () => disposable.dispose();
  }, [editorReady, editorRef, monacoRef]);

  return { zones, toggleZone };
}
