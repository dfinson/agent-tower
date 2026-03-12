/**
 * WorkspaceBrowser — navigable file tree for a job's worktree.
 *
 * Uses a flat list approach with expand/collapse for directories.
 * Fetches file contents when a file is selected.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchWorkspaceFile, fetchWorkspaceFiles } from "../api/client";
import type { WorkspaceEntry } from "../api/types";

interface WorkspaceBrowserProps {
  jobId: string;
}

export default function WorkspaceBrowser({ jobId }: WorkspaceBrowserProps) {
  const [entries, setEntries] = useState<WorkspaceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [fileLoading, setFileLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchWorkspaceFiles(jobId)
      .then((res) => {
        if (!cancelled) setEntries(res.items);
      })
      .catch(() => {
        if (!cancelled) setEntries([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const handleFileClick = useCallback(
    (path: string, entryType: string) => {
      if (entryType === "directory") return;
      setSelectedFile(path);
      setFileLoading(true);
      fetchWorkspaceFile(jobId, path)
        .then((res) => setFileContent(res.content))
        .catch(() => setFileContent("(Unable to load file)"))
        .finally(() => setFileLoading(false));
    },
    [jobId],
  );

  if (loading) {
    return <div style={{ padding: 16, color: "#888" }}>Loading workspace…</div>;
  }

  if (entries.length === 0) {
    return <div style={{ padding: 16, color: "#888" }}>No files found.</div>;
  }

  return (
    <div style={{ display: "flex", height: "100%", fontFamily: "monospace", fontSize: 13 }}>
      {/* File tree */}
      <div
        style={{
          width: 260,
          borderRight: "1px solid #333",
          overflowY: "auto",
          flexShrink: 0,
        }}
      >
        {entries.map((entry) => (
          <button
            type="button"
            key={entry.path}
            onClick={() => handleFileClick(entry.path, entry.type)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              padding: "4px 12px",
              border: "none",
              background: entry.path === selectedFile ? "#264f78" : "transparent",
              color: entry.type === "directory" ? "#e1e4e8" : "#8b949e",
              cursor: entry.type === "file" ? "pointer" : "default",
              fontSize: 12,
            }}
          >
            {entry.type === "directory" ? "📁 " : "📄 "}
            {entry.path}
            {entry.sizeBytes != null && (
              <span style={{ float: "right", color: "#555" }}>
                {formatBytes(entry.sizeBytes)}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* File content viewer */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {selectedFile ? (
          <div>
            <div
              style={{
                padding: "8px 16px",
                borderBottom: "1px solid #333",
                color: "#ccc",
                fontWeight: "bold",
              }}
            >
              {selectedFile}
            </div>
            {fileLoading ? (
              <div style={{ padding: 16, color: "#888" }}>Loading…</div>
            ) : (
              <pre
                style={{
                  margin: 0,
                  padding: 16,
                  color: "#ccc",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {fileContent}
              </pre>
            )}
          </div>
        ) : (
          <div style={{ padding: 16, color: "#555" }}>Select a file to view its contents.</div>
        )}
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
