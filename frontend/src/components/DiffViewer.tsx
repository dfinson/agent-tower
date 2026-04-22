import { useState, useEffect, useCallback, useMemo, useRef, useLayoutEffect } from "react";
import { useNavigate } from "react-router-dom";
import { type LucideIcon, FileCode, FilePlus, FileMinus, FileEdit, MessageSquare, Send, Lock, Check, Minus, Filter, X, Lightbulb, Info, FolderOpen, AlertTriangle, Eye, ArrowUpDown, BookOpenCheck, Columns2 } from "lucide-react";
import { DiffEditor } from "@monaco-editor/react";
import { toast } from "sonner";
import { useStore, selectJobDiffs } from "../store";
import { sendOperatorMessage, resumeJob, continueJob, fetchStepDiff, fetchJobTelemetry } from "../api/client";
import { useIsMobile } from "../hooks/useIsMobile";
import { Spinner } from "./ui/spinner";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";
import { MicButton } from "./VoiceButton";
import { Tooltip } from "./ui/tooltip";
import { useDrag } from "../hooks/useDrag";
import type { DiffFileModel, DiffHunkModel, FileMotivation, HunkMotivation, StepDiffResponse, TestCoModification } from "../api/types";
import { StoryBanner } from "./StoryBanner";
import { BottomSheet } from "./ui/bottom-sheet";

export interface StepFilter {
  /** Relative file paths that belong to this step */
  filePaths: string[];
  /** Human-readable label, e.g. "Edited models.py, views.py" */
  label: string;
  /** Transcript entry seq to scroll back to in the feed */
  scrollToSeq?: number;
  /** SDK turn ID — used to fetch the exact step diff from the API */
  turnId?: string;
}

interface DiffViewerProps {
  jobId: string;
  jobState?: string;
  resolution?: string | null;
  archivedAt?: string | null;
  onAskSent?: () => void;
  stepFilter?: StepFilter | null;
  onClearStepFilter?: () => void;
  onNavigateToStep?: (seq: number, turnId?: string) => void;
}

const STATUS_ICON: Record<string, LucideIcon> = {
  added: FilePlus,
  deleted: FileMinus,
  modified: FileEdit,
  renamed: FileEdit,
};

const STATUS_BADGE: Record<string, string> = {
  added: "text-green-400 border-green-800",
  deleted: "text-red-400 border-red-800",
  modified: "text-blue-400 border-blue-800",
  renamed: "text-yellow-400 border-yellow-800",
};

const STATUS_ICON_CLASS: Record<string, string> = {
  added: "text-green-400",
  deleted: "text-red-400",
  modified: "text-blue-400",
  renamed: "text-yellow-400",
};


function guessLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", kt: "kotlin",
    rb: "ruby", php: "php", cs: "csharp", cpp: "cpp", c: "c", h: "c",
    json: "json", yaml: "yaml", yml: "yaml", toml: "toml",
    md: "markdown", html: "html", css: "css", scss: "scss",
    sql: "sql", sh: "shell", bash: "shell", dockerfile: "dockerfile",
  };
  return map[ext] ?? "plaintext";
}

/** Build a compact span reference for a file's hunks, e.g. "src/foo.ts:L10-L25,L40-L52" */
function fileSpanRef(file: DiffFileModel): string {
  const spans = file.hunks.map((h: DiffHunkModel) => {
    const start = h.newStart;
    const end = h.newStart + h.newLines - 1;
    return start === end ? `L${start}` : `L${start}-L${end}`;
  });
  return `${file.path}:${spans.join(",")}`;
}

/**
 * Displays a file path truncated from the left by path segment when it overflows.
 * Always shows the full path if it fits; otherwise drops leading segments and
 * prepends "…/" until it fits (or only the filename remains).
 */
function TruncatedPath({ path }: { path: string }) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const [displayPath, setDisplayPath] = useState(path);

  const computeTruncation = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const segments = path.split("/");

    for (let start = 0; start < segments.length; start++) {
      const candidate =
        start === 0 ? path : "\u2026/" + segments.slice(start).join("/");
      // Probe the width by temporarily setting textContent
      el.textContent = candidate;
      if (el.scrollWidth <= el.offsetWidth + 1 || start === segments.length - 1) {
        setDisplayPath(candidate);
        return;
      }
    }
  }, [path]);

  useLayoutEffect(() => {
    computeTruncation();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(computeTruncation);
    ro.observe(el);
    return () => ro.disconnect();
  }, [computeTruncation]);

  return (
    <span
      ref={containerRef}
      className="text-xs flex-1 min-w-0 overflow-hidden whitespace-nowrap text-foreground"
      title={path}
    >
      {displayPath}
    </span>
  );
}

/** Determine if the diff is askable; historical jobs create follow-up jobs. */
function computeAskState(): { canAsk: boolean; reason: string | null } {
  // Active jobs accept an operator message. Historical terminal jobs create
  // a follow-up job instead of mutating the original job in place.
  return { canAsk: true, reason: null };
}

export default function DiffViewer({ jobId, jobState, onAskSent, stepFilter, onClearStepFilter, onNavigateToStep }: DiffViewerProps) {
  const navigate = useNavigate();
  const allDiffs = useStore(selectJobDiffs(jobId));
  const isMobile = useIsMobile();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [showAllChanges, setShowAllChanges] = useState(false);
  const [mobileFilePickerOpen, setMobileFilePickerOpen] = useState(false);

  // Step-specific diffs fetched from the API (when turnId is available)
  const [stepDiffs, setStepDiffs] = useState<import("../api/types").DiffFileModel[] | null>(null);
  const [stepDiffsLoading, setStepDiffsLoading] = useState(false);

  // Motivation data from the step-diff API
  const [stepContext, setStepContext] = useState<string | null>(null);
  const [fileMotivations, setFileMotivations] = useState<Record<string, FileMotivation>>({});
  const [hunkMotivations, setHunkMotivations] = useState<Record<string, HunkMotivation>>({});
  const [showIntent, setShowIntent] = useState(true);

  // WS7: Anti-skim — track which files the reviewer has viewed
  const [viewedFiles, setViewedFiles] = useState<Set<number>>(new Set());

  // WS2: Blast radius — context files read but not written
  const [contextFiles, setContextFiles] = useState<{ filePath: string; readCount: number }[]>([]);
  const [contextFilesOpen, setContextFilesOpen] = useState(false);

  // WS5: Test co-modification warnings
  const [testCoMods, setTestCoMods] = useState<TestCoModification[]>([]);

  // WS6: Review complexity
  const [reviewComplexity, setReviewComplexity] = useState<{ tier: string; signals: string[] } | null>(null);

  // WS1: Sort by churn toggle
  const [sortByChurn, setSortByChurn] = useState(false);

  // Split (side-by-side) vs unified (single) diff view
  const [splitView, setSplitView] = useState(false);

  // Fetch step-specific diff from API when filter has a turnId
  useEffect(() => {
    if (!stepFilter?.turnId || showAllChanges) {
      setStepDiffs(null);
      setStepContext(null);
      setFileMotivations({});
      setHunkMotivations({});
      return;
    }
    let cancelled = false;
    setStepDiffsLoading(true);
    fetchStepDiff(jobId, stepFilter.turnId)
      .then((res: StepDiffResponse) => {
        const files = res.changedFiles ?? [];
        if (!cancelled) {
          setStepDiffs(files.length > 0 ? files : null);
          setStepContext(res.stepContext ?? null);
          setFileMotivations(res.fileMotivations ?? {});
          setHunkMotivations(res.hunkMotivations ?? {});
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStepDiffs(null);
          setStepContext(null);
          setFileMotivations({});
          setHunkMotivations({});
        }
      })
      .finally(() => {
        if (!cancelled) setStepDiffsLoading(false);
      });
    return () => { cancelled = true; };
  }, [jobId, stepFilter?.turnId, showAllChanges]);

  // Fetch telemetry for blast radius (context files) + review signals
  useEffect(() => {
    let cancelled = false;
    fetchJobTelemetry(jobId)
      .then((telem) => {
        if (cancelled) return;
        // WS2: Extract read-only context files (read but never written)
        const topFiles = (telem as Record<string, unknown>).fileAccess as { topFiles?: { filePath: string; readCount: number; writeCount: number }[] } | undefined;
        if (topFiles?.topFiles) {
          setContextFiles(
            topFiles.topFiles
              .filter((f) => f.writeCount === 0 && f.readCount > 0)
              .map((f) => ({ filePath: f.filePath, readCount: f.readCount })),
          );
        }
        // WS5: Test co-modifications
        const signals = (telem as Record<string, unknown>).reviewSignals as { testCoModifications?: TestCoModification[] } | undefined;
        if (signals?.testCoModifications) {
          setTestCoMods(signals.testCoModifications);
        }
        // WS6: Review complexity
        const complexity = (telem as Record<string, unknown>).reviewComplexity as { tier: string; signals: string[] } | undefined;
        if (complexity) {
          setReviewComplexity(complexity);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [jobId]);

  // Filter diffs when step filter is active and not toggled to "all"
  const isFiltered = !!stepFilter && !showAllChanges;
  const diffs = useMemo(() => {
    let result: DiffFileModel[];
    if (!isFiltered || !stepFilter) {
      result = allDiffs;
    } else if (stepDiffs !== null) {
      result = stepDiffs;
    } else {
      const filterPaths = new Set(stepFilter.filePaths);
      result = allDiffs.filter((f) =>
        filterPaths.has(f.path) ||
        stepFilter.filePaths.some((fp) => f.path.endsWith(fp) || fp.endsWith(f.path)),
      );
    }
    // WS1: optionally sort by churn (write_count descending)
    if (sortByChurn) {
      return [...result].sort((a, b) => (b.writeCount ?? 0) - (a.writeCount ?? 0));
    }
    return result;
  }, [allDiffs, stepFilter, isFiltered, stepDiffs, sortByChurn]);

  // WS7: Mark file as viewed when selected
  useEffect(() => {
    if (diffs.length > 0 && selectedIdx >= 0 && selectedIdx < diffs.length) {
      setViewedFiles((prev) => {
        if (prev.has(selectedIdx)) return prev;
        const next = new Set(prev);
        next.add(selectedIdx);
        return next;
      });
    }
  }, [selectedIdx, diffs.length]);

  // Build set of test file paths for co-mod warnings
  const testCoModPaths = useMemo(() => {
    const paths = new Set<string>();
    for (const m of testCoMods) {
      for (const f of m.testFiles) paths.add(f);
      for (const f of m.sourceFiles) paths.add(f);
    }
    return paths;
  }, [testCoMods]);

  // Reset selection when filter changes
  useEffect(() => { setSelectedIdx(0); }, [isFiltered, stepFilter]);
  // Reset toggle when filter is cleared externally
  useEffect(() => { if (!stepFilter) { setShowAllChanges(false); setStepDiffs(null); setStepContext(null); setFileMotivations({}); setHunkMotivations({}); } }, [stepFilter]);

  const [original, setOriginal] = useState("");
  const [modified, setModified] = useState("");
  const [loading, setLoading] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const minSidebarWidth = 150;
  const maxSidebarWidth = 400;

  const dragHandlers = useDrag({
    axis: "x",
    onDrag: (delta) => {
      setSidebarWidth(Math.min(maxSidebarWidth, Math.max(minSidebarWidth, sidebarWidth - delta)));
    },
  });

  // Ask-about-diff state — tracked per hunk (key: "fileIdx:hunkIdx")
  const [checkedHunks, setCheckedHunks] = useState<Set<string>>(new Set());
  const [askMsg, setAskMsg] = useState("");
  const [askSending, setAskSending] = useState(false);
  const { canAsk, reason: disabledReason } = computeAskState();
  const isReview = jobState === "review";
  const isTerminal = ["completed", "failed", "canceled"].includes(jobState ?? "");
  const needsResume = isReview || isTerminal;

  const hunkKey = (fi: number, hi: number) => `${fi}:${hi}`;

  const isFileFullyChecked = useCallback(
    (fi: number) => {
      const f = diffs[fi];
      return f != null && f.hunks.length > 0 && f.hunks.every((_, hi) => checkedHunks.has(hunkKey(fi, hi)));
    },
    [diffs, checkedHunks],
  );

  const isFilePartiallyChecked = useCallback(
    (fi: number) => {
      const f = diffs[fi];
      if (!f) return false;
      const n = f.hunks.filter((_, hi) => checkedHunks.has(hunkKey(fi, hi))).length;
      return n > 0 && n < f.hunks.length;
    },
    [diffs, checkedHunks],
  );

  // Voice input state
  const waveformContainerRef = useRef<HTMLDivElement>(null);
  const [micState, setMicState] = useState<"idle" | "recording" | "transcribing">("idle");

  // Monaco editor refs for glyph-margin hunk checkboxes
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const diffEditorRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const monacoRef = useRef<any>(null);
  const decorationIdsRef = useRef<string[]>([]);
  const [hunkLineRanges, setHunkLineRanges] = useState<{ startLine: number; endLine: number }[]>([]);

  // Refs so the glyph-margin click handler always reads current state
  const checkedHunksRef = useRef(checkedHunks);
  checkedHunksRef.current = checkedHunks;
  const selectedIdxRef = useRef(selectedIdx);
  selectedIdxRef.current = selectedIdx;
  const hunkLineRangesRef = useRef(hunkLineRanges);
  hunkLineRangesRef.current = hunkLineRanges;

  // NOTE: diff data is fetched by JobDetailScreen and stored in the Zustand
  // store — no need to duplicate the fetch here.

  const selectedFile = diffs[selectedIdx];

  useEffect(() => {
    if (!selectedFile) return;
    setLoading(true);

    const modifiedParts: string[] = [];
    const originalParts: string[] = [];
    const ranges: { startLine: number; endLine: number }[] = [];
    let lineOffset = 1;

    for (const h of selectedFile.hunks) {
      const lines = h.lines ?? [];
      const nonDel = lines.filter((l) => l.type !== "deletion");
      const nonAdd = lines.filter((l) => l.type !== "addition");
      ranges.push({ startLine: lineOffset, endLine: lineOffset + Math.max(nonDel.length - 1, 0) });
      lineOffset += nonDel.length;
      modifiedParts.push(...nonDel.map((l) => l.content));
      originalParts.push(...nonAdd.map((l) => l.content));
    }

    setOriginal(originalParts.join("\n"));
    setModified(modifiedParts.join("\n"));
    setHunkLineRanges(ranges);
    setLoading(false);
  }, [selectedFile]);

  const toggleFile = useCallback(
    (fi: number) => {
      setCheckedHunks((prev) => {
        const next = new Set(prev);
        const f = diffs[fi];
        if (!f) return next;
        const full = f.hunks.every((_, hi) => next.has(hunkKey(fi, hi)));
        f.hunks.forEach((_, hi) => {
          const k = hunkKey(fi, hi);
          if (full) next.delete(k);
          else next.add(k);
        });
        return next;
      });
    },
    [diffs],
  );

  const toggleHunk = useCallback((fi: number, hi: number) => {
    setCheckedHunks((prev) => {
      const next = new Set(prev);
      const k = hunkKey(fi, hi);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }, []);

  // Inject CSS for glyph-margin checkbox icons (runs once)
  useEffect(() => {
    const id = "hunk-cb-styles";
    if (document.getElementById(id)) return;
    const style = document.createElement("style");
    style.id = id;
    style.textContent = [
      ".hunk-cb-unchecked, .hunk-cb-checked { cursor: pointer !important; }",
      ".hunk-cb-unchecked {",
      "  background: url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none'%3E%3Crect x='1' y='1' width='14' height='14' rx='2.5' stroke='rgba(180,180,200,0.9)' stroke-width='2'/%3E%3C/svg%3E\") center center / 18px no-repeat;",
      "}",
      ".hunk-cb-checked {",
      "  background: url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none'%3E%3Crect x='0.5' y='0.5' width='15' height='15' rx='2.5' fill='%230e639c'/%3E%3Cpath d='M4 8L7 11L12 5' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\") center center / 16px no-repeat;",
      "}",
      ".hunk-selected-line { background: rgba(14,99,156,0.12) !important; }",
      ".hunk-selected-line-margin { border-left: 3px solid rgba(14,99,156,0.7) !important; }",
    ].join("\n");
    document.head.appendChild(style);
    return () => { style.remove(); };
  }, []);

  // Sync glyph-margin decorations whenever selection or file changes
  useEffect(() => {
    const editor = diffEditorRef.current;
    const m = monacoRef.current;
    if (!editor || !m) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!canAsk || hunkLineRanges.length === 0) {
      decorationIdsRef.current = modifiedEditor.deltaDecorations(decorationIdsRef.current, []);
      return;
    }

    // Apply decorations after a short delay to let Monaco process new content
    const applyDecorations = () => {
      const ed = diffEditorRef.current?.getModifiedEditor();
      if (!ed) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const newDecorations: any[] = [];
      hunkLineRanges.forEach((range, hi) => {
        const checked = checkedHunks.has(hunkKey(selectedIdx, hi));
        // Glyph checkbox on the first line of each hunk
        newDecorations.push({
          range: new m.Range(range.startLine, 1, range.startLine, 1),
          options: {
            glyphMarginClassName: checked ? "hunk-cb-checked" : "hunk-cb-unchecked",
            glyphMarginHoverMessage: { value: "Toggle hunk selection" },
          },
        });
        // Background tint + left-border accent across all lines of checked hunks
        if (checked) {
          newDecorations.push({
            range: new m.Range(range.startLine, 1, range.endLine, 1),
            options: {
              className: "hunk-selected-line",
              marginClassName: "hunk-selected-line-margin",
              isWholeLine: true,
            },
          });
        }
      });
      decorationIdsRef.current = ed.deltaDecorations(decorationIdsRef.current, newDecorations);
    };

    // Apply immediately and again after a tick (Monaco may need time to process new models)
    applyDecorations();
    const timer = setTimeout(applyDecorations, 100);
    return () => clearTimeout(timer);
  }, [selectedIdx, checkedHunks, hunkLineRanges, canAsk, modified]);

  // Inject viewZones for hunk-level motivation banners in the modified editor
  const viewZoneIdsRef = useRef<string[]>([]);
  useEffect(() => {
    const editor = diffEditorRef.current;
    if (!editor || !showIntent) return;
    const modifiedEditor = editor.getModifiedEditor();
    if (!modifiedEditor) return;

    const filePath = selectedFile?.path;
    if (!filePath || hunkLineRanges.length === 0) return;

    // Collect motivations for this file's hunks
    const zones: { line: number; title: string; why: string }[] = [];
    hunkLineRanges.forEach((range, hi) => {
      const mot = hunkMotivations[`${filePath}:${hi}`];
      if (mot && (mot.title || mot.why)) {
        zones.push({ line: range.startLine, title: mot.title, why: mot.why });
      }
    });

    if (zones.length === 0) {
      // Clear any existing zones
      modifiedEditor.changeViewZones((accessor: { removeZone: (id: string) => void }) => {
        viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
        viewZoneIdsRef.current = [];
      });
      return;
    }

    // Apply after a short delay so Monaco has processed the models
    const timer = setTimeout(() => {
      const ed = diffEditorRef.current?.getModifiedEditor();
      if (!ed) return;
      ed.changeViewZones((accessor: { removeZone: (id: string) => void; addZone: (zone: { afterLineNumber: number; heightInPx: number; domNode: HTMLElement }) => string }) => {
        // Remove old zones
        viewZoneIdsRef.current.forEach((id: string) => accessor.removeZone(id));
        const newIds: string[] = [];
        for (const z of zones) {
          const domNode = document.createElement("div");
          domNode.className = "intent-banner";
          domNode.style.cssText = "padding: 4px 12px; border-left: 2px solid rgba(14,99,156,0.5); background: rgba(14,99,156,0.06); font-size: 12px; line-height: 1.4; overflow: hidden;";
          const titleSpan = document.createElement("span");
          titleSpan.style.cssText = "font-weight: 500; color: var(--vscode-foreground, #ccc);";
          titleSpan.textContent = z.title;
          domNode.appendChild(titleSpan);
          if (z.why) {
            const whySpan = document.createElement("span");
            whySpan.style.cssText = "margin-left: 8px; color: var(--vscode-descriptionForeground, #999);";
            whySpan.textContent = z.why;
            domNode.appendChild(whySpan);
          }
          const id = accessor.addZone({
            afterLineNumber: z.line - 1,
            heightInPx: 26,
            domNode,
          });
          newIds.push(id);
        }
        viewZoneIdsRef.current = newIds;
      });
    }, 150);

    return () => clearTimeout(timer);
  }, [selectedFile?.path, hunkLineRanges, hunkMotivations, showIntent, modified]);

  // DiffEditor mount handler — wires the glyph-margin click listener
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleEditorMount = useCallback((editor: any, monaco: any) => {
    diffEditorRef.current = editor;
    monacoRef.current = monaco;
    const modifiedEditor = editor.getModifiedEditor();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    modifiedEditor.onMouseDown((e: any) => {
      if (e.target.type !== monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN) return;
      // Prevent Monaco from focusing/scrolling on glyph clicks
      e.event?.preventDefault?.();
      e.event?.stopPropagation?.();
      const lineNumber = e.target.position?.lineNumber;
      if (lineNumber == null) return;
      const ranges = hunkLineRangesRef.current;
      const fi = selectedIdxRef.current;
      for (let hi = 0; hi < ranges.length; hi++) {
        const r = ranges[hi];
        if (r && lineNumber >= r.startLine && lineNumber <= r.endLine) {
          toggleHunk(fi, hi);
          // Blur editor to prevent keyboard popup on mobile / scroll jump on desktop
          (document.activeElement as HTMLElement)?.blur?.();
          break;
        }
      }
    });
  }, [toggleHunk]);

  const handleAskSend = useCallback(async () => {
    if (!askMsg.trim() || checkedHunks.size === 0) return;

    // Group checked hunks by file index
    const fileHunks = new Map<number, number[]>();
    for (const key of checkedHunks) {
      const parts = key.split(":");
      const fi = Number(parts[0]);
      const hi = Number(parts[1]);
      const arr = fileHunks.get(fi) ?? [];
      arr.push(hi);
      fileHunks.set(fi, arr);
    }

    const refs: string[] = [];
    for (const [fi, his] of fileHunks) {
      const file = diffs[fi];
      if (!file) continue;
      // If all hunks selected, use the full file span shorthand
      if (his.length === file.hunks.length) {
        refs.push(fileSpanRef(file));
      } else {
        const spans = his
          .sort((a, b) => a - b)
          .map((hi) => {
            const h = file.hunks[hi];
            if (!h) return null;
            const start = h.newStart;
            const end = h.newStart + h.newLines - 1;
            return start === end ? `L${start}` : `L${start}-L${end}`;
          })
          .filter(Boolean);
        refs.push(`${file.path}:${spans.join(",")}`);
      }
    }

    const contextPrefix = `[Re: changes in ${refs.join("; ")}]\n\n`;
    const fullMessage = contextPrefix + askMsg.trim();

    setAskSending(true);
    try {
      if (needsResume) {
        try {
          await resumeJob(jobId, fullMessage);
        } catch {
          // Worktree gone / unrecoverable — fall back to follow-up job
          const nextJob = await continueJob(jobId, fullMessage);
          toast.success("Follow-up job created");
          navigate(`/jobs/${nextJob.id}`);
        }
      } else {
        await sendOperatorMessage(jobId, fullMessage);
      }
      toast.success("Question sent to agent");
      setAskMsg("");
      setCheckedHunks(new Set());
      onAskSent?.();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setAskSending(false);
    }
  }, [jobId, askMsg, checkedHunks, diffs, needsResume, navigate, onAskSent]);

  const totalAdditions = diffs.reduce((sum, f) => sum + (f.additions ?? 0), 0);
  const totalDeletions = diffs.reduce((sum, f) => sum + (f.deletions ?? 0), 0);

  if (diffs.length === 0 && !stepFilter) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        <p className="text-sm text-muted-foreground">No changes detected</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Step filter banner */}
      {stepFilter && (
        <div className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
          <Filter size={14} className="text-primary shrink-0" />
          <span className="text-xs text-muted-foreground">
            {isFiltered ? (
              <>
                Showing changes from:{" "}
                {stepFilter.scrollToSeq != null && onNavigateToStep ? (
                  <button
                    onClick={() => onNavigateToStep(stepFilter.scrollToSeq!, stepFilter.turnId)}
                    className="text-primary hover:text-primary/80 underline underline-offset-2 decoration-primary/40 hover:decoration-primary transition-colors"
                  >
                    {stepFilter.label}
                  </button>
                ) : (
                  <span className="text-foreground/80">{stepFilter.label}</span>
                )}
              </>
            ) : "Showing all changes"}
          </span>
          <div className="ml-auto flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => setShowAllChanges(!showAllChanges)}
              className={cn(
                "px-2 py-1 md:py-0.5 rounded text-[11px] font-medium transition-colors min-h-[44px] md:min-h-0",
                isFiltered
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "bg-muted/30 text-muted-foreground hover:bg-accent/40 border border-transparent",
              )}
            >
              Step Only
            </button>
            <button
              onClick={() => setShowAllChanges(!showAllChanges)}
              className={cn(
                "px-2 py-1 md:py-0.5 rounded text-[11px] font-medium transition-colors min-h-[44px] md:min-h-0",
                !isFiltered
                  ? "bg-primary/15 text-primary border border-primary/30"
                  : "bg-muted/30 text-muted-foreground hover:bg-accent/40 border border-transparent",
              )}
            >
              All Changes
            </button>
            <button
              onClick={onClearStepFilter}
              className="p-1.5 min-h-[44px] md:min-h-0 min-w-[44px] md:min-w-0 flex items-center justify-center text-muted-foreground/50 hover:text-muted-foreground transition-colors ml-1"
              title="Clear filter"
            >
              <X size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Layer 1: Step context banner — shows WHY this step was performed */}
      {stepContext && isFiltered && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <Lightbulb size={14} className="text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">{stepContext}</p>
        </div>
      )}

      {/* Story banner — collapsible code-review narrative */}
      {!isFiltered && diffs.length > 0 && (
        <StoryBanner jobId={jobId} diffs={diffs} onSelectFile={setSelectedIdx} />
      )}

      {/* WS5: Test co-modification warning */}
      {testCoMods.length > 0 && !isFiltered && (
        <div className="flex items-start gap-2 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3 py-2">
          <AlertTriangle size={14} className="text-yellow-400 shrink-0 mt-0.5" />
          <div className="text-xs text-muted-foreground leading-relaxed">
            <span className="font-medium text-yellow-400">Test co-modification detected</span>
            <span> — {testCoMods.length} step{testCoMods.length > 1 ? "s" : ""} modified both test and source files together. Review test coverage carefully.</span>
          </div>
        </div>
      )}

      {/* WS6: Review complexity badge */}
      {reviewComplexity && reviewComplexity.tier !== "quick" && !isFiltered && (
        <div className="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-1.5">
          <span className={cn(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded",
            reviewComplexity.tier === "deep" ? "bg-red-500/20 text-red-400" : "bg-amber-500/20 text-amber-400",
          )}>
            {reviewComplexity.tier === "deep" ? "Deep Review" : "Standard Review"}
          </span>
          <span className="text-[10px] text-muted-foreground/60">
            {reviewComplexity.signals.map((s) => s.replace(/_/g, " ")).join(" · ")}
          </span>
        </div>
      )}

      {stepDiffsLoading && isFiltered && (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      )}

      {!stepDiffsLoading && diffs.length === 0 && stepFilter && (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <p className="text-sm text-muted-foreground">No matching changes for this step</p>
        </div>
      )}

      {diffs.length > 0 && (
      <>
      {/* Mobile file picker bottom sheet */}
      {isMobile && (
        <BottomSheet open={mobileFilePickerOpen} onClose={() => setMobileFilePickerOpen(false)} title={`${diffs.length} files  +${totalAdditions} -${totalDeletions}`}>
          <div className="flex flex-col -mx-4">
            {diffs.map((file, i) => {
              const Icon = STATUS_ICON[file.status] ?? FileCode;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => { setSelectedIdx(i); setMobileFilePickerOpen(false); }}
                  className={cn(
                    "flex items-center gap-2 px-4 py-3 text-sm transition-colors w-full min-h-[44px]",
                    i === selectedIdx ? "bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <Icon size={14} className={cn("shrink-0", STATUS_ICON_CLASS[file.status])} />
                  <span className="flex-1 min-w-0 text-left truncate text-foreground">{file.path}</span>
                  <span className={cn("text-xs border rounded px-1 shrink-0", STATUS_BADGE[file.status])}>
                    +{file.additions} -{file.deletions}
                  </span>
                </button>
              );
            })}
          </div>
        </BottomSheet>
      )}
      <div className="flex flex-col md:flex-row gap-3 md:gap-0 h-[calc(100dvh-14rem)] md:h-full min-h-[300px]">
        {/* File list sidebar — hidden on mobile, replaced by bottom sheet */}
        <div
          className="hidden md:flex shrink-0 flex-col overflow-hidden rounded-lg border border-border bg-card"
          style={{ width: sidebarWidth }}
        >
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
            <span className="text-xs font-semibold text-muted-foreground">{diffs.length} files</span>
            <div className="flex items-center gap-2">
              {/* WS1: Sort by churn toggle */}
              {diffs.some((f) => (f.writeCount ?? 0) > 1) && (
                <Tooltip content={sortByChurn ? "Sort by file order" : "Sort by edit churn"}>
                  <button
                    onClick={() => setSortByChurn(!sortByChurn)}
                    className={cn(
                      "p-0.5 rounded transition-colors",
                      sortByChurn ? "text-orange-400 hover:text-orange-300" : "text-muted-foreground/40 hover:text-muted-foreground",
                    )}
                  >
                    <ArrowUpDown size={13} />
                  </button>
                </Tooltip>
              )}
              {Object.keys(hunkMotivations).length > 0 && (
                <Tooltip content={showIntent ? "Hide intent annotations" : "Show intent annotations"}>
                  <button
                    onClick={() => setShowIntent(!showIntent)}
                    className={cn(
                      "p-0.5 rounded transition-colors",
                      showIntent ? "text-amber-400 hover:text-amber-300" : "text-muted-foreground/40 hover:text-muted-foreground",
                    )}
                  >
                    <Lightbulb size={13} />
                  </button>
                </Tooltip>
              )}
              <Tooltip content={splitView ? "Unified diff" : "Split diff"}>
                <button
                  onClick={() => setSplitView(!splitView)}
                  className={cn(
                    "p-0.5 rounded transition-colors",
                    splitView ? "text-blue-400 hover:text-blue-300" : "text-muted-foreground/40 hover:text-muted-foreground",
                  )}
                >
                  <Columns2 size={13} />
                </button>
              </Tooltip>
              <span className="text-xs text-green-400">+{totalAdditions}</span>
              <span className="text-xs text-red-400">-{totalDeletions}</span>
              {contextFiles.length > 0 && (
                <span className="text-xs text-blue-400">· {contextFiles.length} read</span>
              )}
            </div>
          </div>
          {/* WS7: Review progress bar */}
          {diffs.length > 1 && (
            <div className="flex items-center gap-1.5 px-3 py-1 border-b border-border/50 bg-muted/10">
              <BookOpenCheck size={11} className="text-muted-foreground/60 shrink-0" />
              <span className="text-[10px] text-muted-foreground/70">{viewedFiles.size}/{diffs.length} reviewed</span>
              <div className="flex-1 h-1 rounded-full bg-muted/30 overflow-hidden">
                <div
                  className="h-full bg-primary/60 rounded-full transition-all duration-300"
                  style={{ width: `${Math.round((viewedFiles.size / diffs.length) * 100)}%` }}
                />
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto">
            {diffs.map((file, i) => {
              const Icon = STATUS_ICON[file.status] ?? FileCode;
              const fileChecked = isFileFullyChecked(i);
              const filePartial = isFilePartiallyChecked(i);
              const fileMot = fileMotivations[file.path];
              const churn = file.writeCount ?? 0;
              const isTestCoMod = testCoModPaths.has(file.path);
              const isViewed = viewedFiles.has(i);
              return (
                <div key={i} className="flex flex-col">
                  <div
                    className={cn(
                      "flex items-center gap-1.5 px-2 py-2 text-sm transition-colors w-full",
                      i === selectedIdx ? "bg-accent" : "hover:bg-accent/50",
                    )}
                  >
                    {/* WS7: Unviewed indicator */}
                    {!isViewed && i !== selectedIdx ? (
                      <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-blue-400" />
                    ) : (
                      <span className="shrink-0 w-1.5" />
                    )}
                    {/* File checkbox — tri-state: unchecked / partial (minus) / fully checked */}
                    {canAsk ? (
                      <Tooltip content="Select to ask about this file's changes">
                        <button
                          type="button"
                          onClick={() => toggleFile(i)}
                          className={cn(
                            "shrink-0 w-5 h-5 md:w-4 md:h-4 rounded-[3px] border-2 flex items-center justify-center transition-colors cursor-pointer",
                            fileChecked || filePartial
                              ? "bg-primary border-primary text-primary-foreground"
                              : "border-muted-foreground/60 hover:border-foreground/80",
                          )}
                        >
                          {fileChecked && <Check size={12} strokeWidth={3} />}
                          {filePartial && <Minus size={12} strokeWidth={3} />}
                        </button>
                      </Tooltip>
                    ) : (
                      <span className="shrink-0 w-5 md:w-4" />
                    )}
                    <button
                      type="button"
                      onClick={() => setSelectedIdx(i)}
                      className="flex items-center gap-2 flex-1 min-w-0 text-left"
                    >
                      <Icon size={14} className={cn("shrink-0", STATUS_ICON_CLASS[file.status])} />
                      {/* WS5: Test co-mod warning */}
                      {isTestCoMod && (
                        <Tooltip content="Modified alongside test files in the same step">
                          <AlertTriangle size={11} className="shrink-0 text-yellow-400" />
                        </Tooltip>
                      )}
                      {fileMot && (
                        <Tooltip
                          content={
                            <div className="max-w-[280px]">
                              <p className="font-medium text-foreground">{fileMot.title}</p>
                              {fileMot.why && (
                                <p className="mt-0.5 text-muted-foreground">{fileMot.why}</p>
                              )}
                              {(fileMot.unmatchedEdits?.length ?? 0) > 0 && (
                                <div className="mt-1.5 pt-1.5 border-t border-border">
                                  <p className="text-[10px] text-muted-foreground/60 mb-1">Other edits:</p>
                                  {fileMot.unmatchedEdits.map((e, ei) => (
                                    <p key={ei} className="text-muted-foreground">{e.title}</p>
                                  ))}
                                </div>
                              )}
                            </div>
                          }
                          side="right"
                        >
                          <Info size={11} className="shrink-0 text-amber-400/70" />
                        </Tooltip>
                      )}
                      <TruncatedPath path={file.path} />
                      {/* WS1: Churn badge */}
                      {churn >= 2 && (
                        <Tooltip content={`${churn} writes${file.retryCount ? `, ${file.retryCount} retries` : ""}`}>
                          <span className={cn(
                            "text-[9px] font-bold rounded px-1 shrink-0",
                            churn >= 4 ? "bg-red-500/20 text-red-400" : "bg-amber-500/20 text-amber-400",
                          )}>
                            {churn}×
                          </span>
                        </Tooltip>
                      )}
                      <span className={cn("text-xs border rounded px-1 hidden md:inline", STATUS_BADGE[file.status])}>
                        +{file.additions} -{file.deletions}
                      </span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* WS2: Context files read but not modified */}
          {contextFiles.length > 0 && (
            <div className="border-t border-border">
              <button
                type="button"
                onClick={() => setContextFilesOpen(!contextFilesOpen)}
                className="flex items-center gap-1.5 w-full px-3 py-1.5 text-left hover:bg-accent/30 transition-colors"
              >
                <Eye size={11} className="text-blue-400/70 shrink-0" />
                <span className="text-[10px] text-muted-foreground">Context files read ({contextFiles.length})</span>
              </button>
              {contextFilesOpen && (
                <div className="max-h-32 overflow-y-auto">
                  {contextFiles.map((cf, ci) => (
                    <div key={ci} className="flex items-center gap-2 px-3 py-1 text-[10px] text-muted-foreground/70">
                      <FileCode size={10} className="shrink-0 text-blue-400/40" />
                      <span className="flex-1 min-w-0 truncate" title={cf.filePath}>
                        {cf.filePath}
                      </span>
                      <span className="text-blue-400/50 shrink-0">{cf.readCount}×</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Resize handle — desktop only */}
        {!isMobile && (
          <div
            className="hidden md:flex items-center justify-center w-1.5 shrink-0 cursor-col-resize rounded-full bg-border hover:bg-primary/60 transition-colors active:bg-primary"
            {...dragHandlers}
          />
        )}

        {/* Monaco Diff Editor */}
        <div className="flex-1 min-h-0 overflow-hidden rounded-lg border border-border bg-card relative">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <Spinner />
            </div>
          ) : selectedFile ? (
            <>
            <DiffEditor
              original={original}
              modified={modified}
              language={guessLanguage(selectedFile.path)}
              theme="vs-dark"
              onMount={handleEditorMount}
              options={{
                readOnly: true,
                domReadOnly: true,
                minimap: { enabled: false },
                renderSideBySide: splitView && !isMobile,
                scrollBeyondLastLine: false,
                fontSize: isMobile ? 12 : 13,
                lineNumbersMinChars: 3,
                glyphMargin: canAsk,
                lineDecorationsWidth: 4,
                folding: true,
              }}
            />
            {/* Mobile floating file picker button */}
            {isMobile && (
              <button
                onClick={() => setMobileFilePickerOpen(true)}
                className="absolute top-2 right-2 z-10 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-border bg-card/90 backdrop-blur-sm text-xs font-medium text-muted-foreground hover:text-foreground shadow-sm transition-colors"
              >
                <FolderOpen size={13} />
                <span className="max-w-[120px] truncate">{selectedFile.path.split("/").pop()}</span>
                <span className="text-muted-foreground/60">{selectedIdx + 1}/{diffs.length}</span>
              </button>
            )}
            </>
          ) : null}
        </div>
      </div>
      </>
      )}

      {/* Ask-about-diff bar */}
      {canAsk && checkedHunks.size > 0 && (
        <div className="flex flex-col gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 animate-in slide-in-from-bottom-2 duration-200">
          <div className="flex items-center gap-2">
            <MessageSquare size={16} className="text-primary shrink-0" />
            <span className="text-xs text-muted-foreground">
              {checkedHunks.size} hunk{checkedHunks.size !== 1 ? "s" : ""} selected
              {" across "}
              {new Set(Array.from(checkedHunks).map((k) => k.split(":")[0])).size}
              {" file"}
              {new Set(Array.from(checkedHunks).map((k) => k.split(":")[0])).size !== 1 ? "s" : ""}
            </span>
          </div>

          {/* Waveform strip — always mounted for WaveSurfer stability, shown only during recording */}
          <div className={cn(
            "rounded border border-blue-600/50 bg-card px-3 py-1",
            micState === "recording" ? "block" : "hidden",
          )}>
            <div ref={waveformContainerRef} />
          </div>

          {/* Transcribing indicator */}
          {micState === "transcribing" && (
            <div className="flex items-center gap-2 px-1 text-sm text-muted-foreground">
              <Spinner size="sm" />
              <span>Transcribing…</span>
            </div>
          )}

          <div className="flex items-end gap-2">
            <div className="relative flex-1">
              <textarea
                placeholder="Ask about these changes…"
                value={askMsg}
                onChange={(e) => {
                  setAskMsg(e.currentTarget.value);
                  e.currentTarget.style.height = "auto";
                  e.currentTarget.style.height = Math.min(e.currentTarget.scrollHeight, isMobile ? 240 : 160) + "px";
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !isMobile && !e.shiftKey) {
                    e.preventDefault();
                    handleAskSend();
                  }
                }}
                disabled={askSending || micState !== "idle"}
                rows={1}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-base md:text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 resize-none pr-8 overflow-y-auto"
                style={{ maxHeight: isMobile ? 240 : 160 }}
              />
              <div className="absolute right-2 bottom-1.5">
                <MicButton
                  onTranscript={(t) => setAskMsg((prev) => (prev ? prev + " " : "") + t)}
                  onStateChange={setMicState}
                  waveformContainerRef={waveformContainerRef}
                />
              </div>
            </div>
            <Button
              size="sm"
              onClick={handleAskSend}
              disabled={askSending || !askMsg.trim() || micState !== "idle"}
              loading={askSending}
              className="h-8 gap-1 shrink-0"
            >
              <Send size={14} />
              Ask
            </Button>
          </div>
        </div>
      )}

      {/* Disabled state hint */}
      {!canAsk && (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
          <Lock size={14} className="text-muted-foreground shrink-0" />
          <span className="text-xs text-muted-foreground">
            {disabledReason} — asking about changes is only available for pending diffs
          </span>
        </div>
      )}
    </div>
  );
}
