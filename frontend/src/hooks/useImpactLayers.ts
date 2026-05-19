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
}

export interface ImpactZoneData {
  symbolName: string;
  afterLine: number;
  summary: string;
  totalReferences: number;
  callers: ImpactCaller[];
  expanded: boolean;
  category: string;
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
  jobId: _jobId,
  file,
  enabled,
  editorRef,
  monacoRef,
  editorReady,
}: UseImpactLayersOpts) {
  void _jobId; // reserved for future use (e.g. per-job cache key)
  const [zones, setZones] = useState<ImpactZoneData[]>([]);
  const viewZoneIdsRef = useRef<string[]>([]);
  const zoneDomsRef = useRef<Map<string, HTMLElement>>(new Map());

  // Build impact zones directly from embedded symbol data (CodeRecon semantic_diff).
  // No API calls needed — data arrives with the diff response.
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

    const newZones: ImpactZoneData[] = symbols
      .filter((sym) => sym.refCount > 0)
      .map((sym) => {
        // Place view zone after the last line of the symbol
        const afterLine = sym.lineRange?.[1] ?? 1;

        // Build caller list from ref_tiers breakdown
        const callers: ImpactCaller[] = [];
        for (const testFile of sym.testFiles) {
          callers.push({
            symbol: "",
            file: testFile,
            line: null,
            tier: "test",
            isTest: true,
          });
        }

        // Build summary with tier breakdown
        const tierParts: string[] = [];
        for (const [tier, count] of Object.entries(sym.refTiers)) {
          if (count > 0) tierParts.push(`${count} ${tier}`);
        }
        const summary = tierParts.length > 0
          ? `${sym.refCount} ref(s): ${tierParts.join(", ")}`
          : `${sym.refCount} reference(s)`;

        return {
          symbolName: sym.symbol,
          afterLine,
          summary,
          totalReferences: sym.refCount,
          callers,
          expanded: false,
          category: sym.category,
        };
      });

    setZones(newZones);
  }, [file, enabled]);

  // Inject view zones into the modified editor
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !editorReady || !enabled) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    // Clear existing zones
    modifiedEditor.changeViewZones((accessor: any) => {
      viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
      viewZoneIdsRef.current = [];
    });
    zoneDomsRef.current.clear();

    if (zones.length === 0) return;

    const timer = setTimeout(() => {
      const ed = editorRef.current?.getModifiedEditor();
      if (!ed) return;

      ed.changeViewZones((accessor: any) => {
        viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
        const newIds: string[] = [];

        for (const zone of zones) {
          const domNode = document.createElement("div");
          domNode.className = "impact-zone-container";
          domNode.dataset.symbol = zone.symbolName;

          // Category badge color
          const categoryClass = zone.category === "breaking" ? "impact-badge-breaking" : "";

          // Collapsed header
          const testCount = zone.callers.filter((c) => c.isTest).length;
          domNode.innerHTML = `
            <div class="impact-zone-header" data-symbol="${escapeHtml(zone.symbolName)}">
              <span class="impact-chevron">▶</span>
              <span class="impact-badge ${categoryClass}">IMPACT</span>
              <span class="impact-summary">${escapeHtml(zone.summary)}</span>
              ${testCount > 0 ? `<span class="impact-test-pill">${testCount} test${testCount > 1 ? "s" : ""}</span>` : ""}
            </div>
            <div class="impact-zone-body" style="display: none;">
              ${zone.callers.slice(0, 10).map((c) => `
                <div class="impact-caller-card">
                  <span class="impact-caller-dot ${c.isTest ? "test" : "source"}"></span>
                  <span class="impact-caller-name">${escapeHtml(c.symbol || "(test)")}</span>
                  <span class="impact-caller-loc">${escapeHtml(c.file)}${c.line ? `:${c.line}` : ""}</span>
                </div>
              `).join("")}
              ${zone.callers.length > 10 ? `<div class="impact-more">+${zone.callers.length - 10} more</div>` : ""}
            </div>
          `;

          // Toggle expand/collapse on header click
          const header = domNode.querySelector(".impact-zone-header");
          const body = domNode.querySelector(".impact-zone-body") as HTMLElement;
          const chevron = domNode.querySelector(".impact-chevron");
          header?.addEventListener("click", () => {
            const isExpanded = body.style.display !== "none";
            body.style.display = isExpanded ? "none" : "block";
            if (chevron) chevron.textContent = isExpanded ? "▶" : "▼";
            // Relayout view zone height
            ed.changeViewZones((_: any) => {
              // Force re-layout by removing and re-adding
            });
          });

          zoneDomsRef.current.set(zone.symbolName, domNode);

          const id = accessor.addZone({
            afterLineNumber: zone.afterLine,
            heightInPx: 28,
            domNode,
            suppressMouseDown: false,
          });
          newIds.push(id);
        }
        viewZoneIdsRef.current = newIds;
      });
    }, 200);

    return () => clearTimeout(timer);
  }, [zones, enabled, editorReady, editorRef, monacoRef]);

  const toggleZone = useCallback((symbolName: string) => {
    setZones((prev) =>
      prev.map((z) => (z.symbolName === symbolName ? { ...z, expanded: !z.expanded } : z)),
    );
  }, []);

  return { zones, toggleZone };
}
