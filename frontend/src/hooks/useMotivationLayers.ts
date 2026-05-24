/**
 * Hook: useMotivationLayers
 *
 * Fetches job-level motivation data and injects Monaco view zones
 * with "WHY THIS CHANGED" blocks after each changed symbol.
 */

import { useEffect, useRef, useState } from "react";
import { fetchJobMotivations } from "../api/client";
import type { DiffFileModel, FileMotivation, HunkMotivation, JobMotivationsResponse } from "../api/types";

/** Escape HTML special characters to prevent XSS when inserting into innerHTML. */
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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

  // Fetch job-level motivations once (only if step-level not provided)
  useEffect(() => {
    if (stepFileMotivations) return;
    let cancelled = false;
    fetchJobMotivations(jobId)
      .then((res) => { if (!cancelled) setJobMotivations(res); })
      .catch(() => { if (!cancelled) setJobMotivations(null); });
    return () => { cancelled = true; };
  }, [jobId, stepFileMotivations]);

  // Inject view zones
  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !editorReady) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    modifiedEditor.changeViewZones((accessor: any) => {
      viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
      viewZoneIdsRef.current = [];

      if (!enabled || !file) return;

      // Determine which motivation source to use
      const fileMots = stepFileMotivations || jobMotivations?.fileMotivations || {};
      const hunkMots = stepHunkMotivations || jobMotivations?.hunkMotivations || {};

      // Collect motivation zones for this file
      const filePath = file.path;
      const zones: { afterLine: number; title: string; why: string }[] = [];

      // File-level motivation — place AFTER the last line of the first hunk
      const fileMot = fileMots[filePath];
      if (fileMot && fileMot.why) {
        const lastHunk = file.hunks[file.hunks.length - 1];
        if (lastHunk) {
          zones.push({
            afterLine: lastHunk.newStart + lastHunk.newLines - 1,
            title: fileMot.title || "Why this changed",
            why: fileMot.why,
          });
        }
      }

      // Hunk-level motivations — place AFTER the hunk's last added line
      file.hunks.forEach((hunk, hi) => {
        const mot = hunkMots[`${filePath}:${hi}`];
        if (mot && mot.why) {
          zones.push({
            afterLine: hunk.newStart + hunk.newLines - 1,
            title: mot.title || "Why this changed",
            why: mot.why,
          });
        }
      });

      if (zones.length === 0) return;

      const newIds: string[] = [];
      for (const z of zones) {
        const domNode = document.createElement("div");
        domNode.className = "motivation-zone";
        domNode.innerHTML = `
          <div class="mot-label">${escapeHtml(z.title)}</div>
          <div class="mot-text">${escapeHtml(z.why)}</div>
        `;

        const textLines = Math.max(1, Math.ceil(z.why.length / 90));
        const heightInPx = 14 + (textLines * 16) + 12;

        const id = accessor.addZone({
          afterLineNumber: z.afterLine,
          heightInPx,
          domNode,
          suppressMouseDown: true,
        });
        newIds.push(id);
      }
      viewZoneIdsRef.current = newIds;
    });
  }, [file, enabled, editorReady, editorRef, jobMotivations, stepFileMotivations, stepHunkMotivations]);
}
