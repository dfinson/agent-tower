/**
 * Hook: useImpactLayers
 *
 * Fetches impact graph data for symbols in the active diff file and
 * injects Monaco view zones showing collapsed/expandable impact panels
 * below the relevant lines.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { fetchImpactGraph } from "../api/client";
import type { DiffFileModel, DiffHunkModel } from "../api/types";

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
}

interface UseImpactLayersOpts {
  jobId: string;
  file: DiffFileModel | undefined;
  enabled: boolean;
  editorRef: React.MutableRefObject<any>;
  monacoRef: React.MutableRefObject<any>;
  editorReady: boolean;
}

/** Extract symbol-like names from modified lines of a hunk (very simple heuristic). */
function extractSymbolsFromHunks(hunks: DiffHunkModel[]): { name: string; afterLine: number }[] {
  const symbols: { name: string; afterLine: number }[] = [];
  const seen = new Set<string>();

  for (const hunk of hunks) {
    let currentLine = hunk.newStart;
    for (const line of hunk.lines) {
      if (line.type === "deletion") continue;
      if (line.type === "addition" || line.type === "context") {
        // Match function/method/class definitions
        const match = line.content.match(
          /^\s*(?:(?:async\s+)?def|function|class|export\s+(?:default\s+)?(?:function|class)|(?:public|private|protected)\s+(?:static\s+)?(?:async\s+)?)\s+(\w+)/,
        );
        const symName = match?.[1];
        if (symName && !seen.has(symName)) {
          seen.add(symName);
          // The impact zone goes after the last line of this symbol's hunk
          symbols.push({ name: symName, afterLine: hunk.newStart + hunk.newLines - 1 });
        }
        currentLine++;
      }
    }
  }
  return symbols;
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

  // Fetch impact data for symbols detected in the file's hunks
  useEffect(() => {
    if (!file || !enabled) {
      setZones([]);
      return;
    }

    const symbols = extractSymbolsFromHunks(file.hunks);
    if (symbols.length === 0) {
      setZones([]);
      return;
    }

    let cancelled = false;

    Promise.all(
      symbols.map(async (sym) => {
        try {
          const result = await fetchImpactGraph(jobId, sym.name);
          if (cancelled || !result.available) return null;
          const zone: ImpactZoneData = {
            symbolName: sym.name,
            afterLine: sym.afterLine,
            summary: result.summary || `${result.totalReferences} reference(s)`,
            totalReferences: result.totalReferences,
            callers: (result.references || []).map((r) => ({
              symbol: r.symbol,
              file: r.file,
              line: r.line ?? null,
              tier: r.tier,
              isTest: r.isTest,
            })),
            expanded: false,
          };
          return zone;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (!cancelled) {
        setZones(results.filter((r): r is ImpactZoneData => r != null && r.totalReferences > 0));
      }
    });

    return () => { cancelled = true; };
  }, [jobId, file, enabled]);

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

          // Collapsed header
          const failCount = zone.callers.filter((c) => c.isTest).length;
          domNode.innerHTML = `
            <div class="impact-zone-header" data-symbol="${zone.symbolName}">
              <span class="impact-chevron">▶</span>
              <span class="impact-badge">IMPACT</span>
              <span class="impact-summary">${zone.summary}</span>
              ${failCount > 0 ? `<span class="impact-fail-pill">${failCount} test${failCount > 1 ? "s" : ""}</span>` : ""}
            </div>
            <div class="impact-zone-body" style="display: none;">
              ${zone.callers.slice(0, 10).map((c) => `
                <div class="impact-caller-card">
                  <span class="impact-caller-dot ${c.isTest ? "test" : "source"}"></span>
                  <span class="impact-caller-name">${c.symbol}</span>
                  <span class="impact-caller-loc">${c.file}${c.line ? `:${c.line}` : ""}</span>
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
