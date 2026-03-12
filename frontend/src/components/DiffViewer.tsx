/**
 * DiffViewer — displays structured diff output with file list and hunk details.
 *
 * Uses a simple text-based diff view. File list on the left, diff content on the right.
 */

import { useEffect, useMemo, useState } from "react";
import type { DiffFileModel } from "../api/types";
import { selectJobDiffs, useTowerStore } from "../store";

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

export default function DiffViewer({ jobId }: DiffViewerProps) {
  const selector = useMemo(() => selectJobDiffs(jobId), [jobId]);
  const files = useTowerStore(selector);
  const [selectedIdx, setSelectedIdx] = useState(0);

  useEffect(() => {
    setSelectedIdx((prev) => (prev >= files.length ? 0 : prev));
  }, [files.length]);

  const selectedFile = files[selectedIdx] as DiffFileModel | undefined;

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
    <div style={{ display: "flex", height: "100%", fontFamily: "monospace", fontSize: 13 }}>
      {/* File list sidebar */}
      <div
        style={{
          width: 260,
          borderRight: "1px solid #333",
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        <div style={{ padding: "8px 12px", borderBottom: "1px solid #333", color: "#ccc" }}>
          {files.length} file{files.length !== 1 ? "s" : ""} changed
          <span style={{ color: "#2ea043", marginLeft: 8 }}>+{totalStats.additions}</span>
          <span style={{ color: "#f85149", marginLeft: 4 }}>-{totalStats.deletions}</span>
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
            <span style={{ color: statusColor(file.status), marginRight: 6 }}>
              {statusIcon(file.status)}
            </span>
            {file.path}
            <span style={{ float: "right", color: "#888" }}>
              +{file.additions} -{file.deletions}
            </span>
          </button>
        ))}
      </div>

      {/* Diff content */}
      <div style={{ flex: 1, overflowY: "auto", padding: 0 }}>
        {selectedFile && (
          <div>
            <div
              style={{
                padding: "8px 16px",
                borderBottom: "1px solid #333",
                color: "#ccc",
                fontWeight: "bold",
              }}
            >
              {selectedFile.path}
            </div>
            {selectedFile.hunks.map((hunk, hunkIdx) => (
              <div key={`${selectedFile.path}-hunk-${hunkIdx}`}>
                <div
                  style={{
                    padding: "4px 16px",
                    background: "#1c2128",
                    color: "#8b949e",
                    borderBottom: "1px solid #333",
                  }}
                >
                  @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
                </div>
                {hunk.lines.map((line, lineIdx) => {
                  let bg = "transparent";
                  let color = "#ccc";
                  let prefix = " ";
                  if (line.type === "addition") {
                    bg = "rgba(46, 160, 67, 0.15)";
                    color = "#2ea043";
                    prefix = "+";
                  } else if (line.type === "deletion") {
                    bg = "rgba(248, 81, 73, 0.15)";
                    color = "#f85149";
                    prefix = "-";
                  }
                  return (
                    <div
                      key={`${selectedFile.path}-${hunkIdx}-${lineIdx}`}
                      style={{
                        padding: "0 16px",
                        background: bg,
                        color,
                        whiteSpace: "pre-wrap",
                        lineHeight: "20px",
                      }}
                    >
                      {prefix}
                      {line.content}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
