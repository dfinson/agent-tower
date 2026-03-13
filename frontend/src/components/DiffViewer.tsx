/**
 * DiffViewer — displays structured diff output with Monaco DiffEditor.
 *
 * File sidebar on the left, Monaco DiffEditor on the right.
 * Diff content is lazy-loaded per file (only builds original/modified for selected file).
 */

import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type { DiffFileModel } from "../api/types";
import { selectJobDiffs, useTowerStore } from "../store";

const DiffEditor = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.DiffEditor })),
);

interface DiffViewerProps {
  jobId: string;
}

function statusIcon(status: string): string {
  switch (status) {
    case "added":
      return "A";
    case "deleted":
      return "D";
    case "renamed":
      return "R";
    default:
      return "M";
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "added":
      return "#2ea043";
    case "deleted":
      return "#f85149";
    case "renamed":
      return "#d29922";
    default:
      return "#58a6ff";
  }
}

/** Reconstruct original and modified text from hunk lines. */
function buildDiffTexts(file: DiffFileModel): {
  original: string;
  modified: string;
} {
  const origLines: string[] = [];
  const modLines: string[] = [];
  for (const hunk of file.hunks) {
    for (const line of hunk.lines) {
      if (line.type === "context") {
        origLines.push(line.content);
        modLines.push(line.content);
      } else if (line.type === "deletion") {
        origLines.push(line.content);
      } else if (line.type === "addition") {
        modLines.push(line.content);
      }
    }
  }
  return { original: origLines.join("\n"), modified: modLines.join("\n") };
}

/** Guess Monaco language from file extension. */
function guessLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    py: "python",
    json: "json",
    md: "markdown",
    css: "css",
    html: "html",
    yml: "yaml",
    yaml: "yaml",
    sql: "sql",
    sh: "shell",
    bash: "shell",
    toml: "ini",
    rs: "rust",
    go: "go",
  };
  return map[ext] ?? "plaintext";
}

export default function DiffViewer({ jobId }: DiffViewerProps) {
  const selector = useMemo(() => selectJobDiffs(jobId), [jobId]);
  const files = useTowerStore(selector);
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => {
    setSelectedIdx((prev) => (prev >= files.length ? 0 : prev));
  }, [files.length]);

  const selectedFile = files[selectedIdx] as DiffFileModel | undefined;

  // Lazy: only compute diff texts for the currently selected file
  const diffTexts = useMemo(
    () => (selectedFile ? buildDiffTexts(selectedFile) : null),
    [selectedFile],
  );

  const totalStats = useMemo(() => {
    let additions = 0;
    let deletions = 0;
    for (const f of files) {
      additions += f.additions;
      deletions += f.deletions;
    }
    return { additions, deletions };
  }, [files]);

  if (files.length === 0) {
    return (
      <div style={{ padding: 16, color: "#888" }}>No changes detected.</div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        height: "100%",
        fontFamily: "monospace",
        fontSize: 13,
      }}
    >
      {/* File list sidebar */}
      <div
        style={{
          width: 260,
          borderRight: "1px solid #333",
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            padding: "8px 12px",
            borderBottom: "1px solid #333",
            color: "#ccc",
          }}
        >
          {files.length} file{files.length !== 1 ? "s" : ""} changed
          <span style={{ color: "#2ea043", marginLeft: 8 }}>
            +{totalStats.additions}
          </span>
          <span style={{ color: "#f85149", marginLeft: 4 }}>
            -{totalStats.deletions}
          </span>
        </div>
        {files.map((file, idx) => (
          <button
            type="button"
            key={file.path}
            onClick={() => setSelectedIdx(idx)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "6px 12px",
              border: "none",
              background: idx === selectedIdx ? "#264f78" : "transparent",
              color: "#ccc",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            <span
              style={{ color: statusColor(file.status), marginRight: 6 }}
            >
              {statusIcon(file.status)}
            </span>
            {file.path}
            <span style={{ float: "right", color: "#888" }}>
              +{file.additions} -{file.deletions}
            </span>
          </button>
        ))}
      </div>

      {/* Monaco DiffEditor — lazy loaded */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {selectedFile && diffTexts && (
          <Suspense
            fallback={
              <div style={{ padding: 16, color: "#888" }}>
                Loading diff editor…
              </div>
            }
          >
            <DiffEditor
              original={diffTexts.original}
              modified={diffTexts.modified}
              language={guessLanguage(selectedFile.path)}
              theme="vs-dark"
              options={{
                readOnly: true,
                renderSideBySide: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 13,
                lineNumbers: "on",
              }}
            />
          </Suspense>
        )}
      </div>
    </div>
  );
}
