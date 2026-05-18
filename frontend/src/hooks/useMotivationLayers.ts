/**
 * Hook: useMotivationLayers
 *
 * Fetches job-level motivation data and injects Monaco view zones
 * with "WHY THIS CHANGED" blocks after each changed symbol.
 */

import { useEffect, useRef, useState } from "react";
import { fetchJobMotivations } from "../api/client";
import type { DiffFileModel, FileMotivation, HunkMotivation, JobMotivationsResponse } from "../api/types";

interface UseMotivationLayersOpts {
  jobId: string;
  file: DiffFileModel | undefined;
  enabled: boolean;
  editorRef: React.MutableRefObject<any>;
  editorReady: boolean;
  /** If step-level motivations are already available, use those instead */
  stepFileMotivations?: Record<string, FileMotivation>;
  stepHunkMotivations?: Record<string, HunkMotivation>;
}

export function useMotivationLayers({
  jobId,
  file,
  enabled,
  editorRef,
  editorReady,
  stepFileMotivations,
  stepHunkMotivations,
}: UseMotivationLayersOpts) {
  const [jobMotivations, setJobMotivations] = useState<JobMotivationsResponse | null>(null);
  const viewZoneIdsRef = useRef<string[]>([]);

  // Fetch job-level motivations (only if step-level not provided)
  useEffect(() => {
    if (!enabled || stepFileMotivations) return;
    let cancelled = false;
    fetchJobMotivations(jobId)
      .then((res) => { if (!cancelled) setJobMotivations(res); })
      .catch(() => { if (!cancelled) setJobMotivations(null); });
    return () => { cancelled = true; };
  }, [jobId, enabled, stepFileMotivations]);

  // Inject view zones
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !editorReady || !enabled || !file) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    // Determine which motivation source to use
    const fileMotivations = stepFileMotivations || jobMotivations?.fileMotivations || {};
    const hunkMotivations = stepHunkMotivations || jobMotivations?.hunkMotivations || {};

    // Collect motivation zones for this file
    const filePath = file.path;
    const zones: { afterLine: number; title: string; why: string }[] = [];

    // File-level motivation
    const fileMot = fileMotivations[filePath];
    if (fileMot && fileMot.why) {
      // Place after the last hunk's last line
      const lastHunk = file.hunks[file.hunks.length - 1];
      if (lastHunk) {
        zones.push({
          afterLine: lastHunk.newStart + lastHunk.newLines - 1,
          title: fileMot.title || "WHY THIS CHANGED",
          why: fileMot.why,
        });
      }
    }

    // Hunk-level motivations
    file.hunks.forEach((hunk, hi) => {
      const mot = hunkMotivations[`${filePath}:${hi}`];
      if (mot && mot.why) {
        zones.push({
          afterLine: hunk.newStart + hunk.newLines - 1,
          title: mot.title || "WHY THIS CHANGED",
          why: mot.why,
        });
      }
    });

    // Clear existing
    modifiedEditor.changeViewZones((accessor: any) => {
      viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
      viewZoneIdsRef.current = [];
    });

    if (zones.length === 0) return;

    const timer = setTimeout(() => {
      const ed = editorRef.current?.getModifiedEditor();
      if (!ed) return;
      ed.changeViewZones((accessor: any) => {
        viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
        const newIds: string[] = [];

        for (const z of zones) {
          const domNode = document.createElement("div");
          domNode.className = "motivation-zone";
          domNode.innerHTML = `
            <span class="motivation-label">${z.title}</span>
            <span class="motivation-text">${z.why}</span>
          `;

          const id = accessor.addZone({
            afterLineNumber: z.afterLine,
            heightInPx: 28,
            domNode,
            suppressMouseDown: true,
          });
          newIds.push(id);
        }
        viewZoneIdsRef.current = newIds;
      });
    }, 200);

    return () => clearTimeout(timer);
  }, [file, enabled, editorReady, editorRef, jobMotivations, stepFileMotivations, stepHunkMotivations]);
}
