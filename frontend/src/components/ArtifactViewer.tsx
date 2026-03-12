/**
 * ArtifactViewer — lists artifacts for a job with download links.
 */

import { useEffect, useState } from "react";
import { downloadArtifactUrl, fetchArtifacts } from "../api/client";
import type { ArtifactResponse } from "../api/types";

interface ArtifactViewerProps {
  jobId: string;
}

export default function ArtifactViewer({ jobId }: ArtifactViewerProps) {
  const [artifacts, setArtifacts] = useState<ArtifactResponse[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchArtifacts(jobId)
      .then((res) => {
        if (!cancelled) setArtifacts(res.items);
      })
      .catch(() => {
        if (!cancelled) setArtifacts([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (loading) {
    return <div style={{ padding: 16, color: "#888" }}>Loading artifacts…</div>;
  }

  if (artifacts.length === 0) {
    return <div style={{ padding: 16, color: "#888" }}>No artifacts available.</div>;
  }

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ color: "#ccc", margin: "0 0 12px" }}>Artifacts</h3>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #333", color: "#8b949e", textAlign: "left" }}>
            <th style={{ padding: "6px 8px" }}>Name</th>
            <th style={{ padding: "6px 8px" }}>Type</th>
            <th style={{ padding: "6px 8px" }}>Size</th>
            <th style={{ padding: "6px 8px" }}>Created</th>
            <th style={{ padding: "6px 8px" }}></th>
          </tr>
        </thead>
        <tbody>
          {artifacts.map((a) => (
            <tr key={a.id} style={{ borderBottom: "1px solid #222" }}>
              <td style={{ padding: "6px 8px", color: "#ccc" }}>{a.name}</td>
              <td style={{ padding: "6px 8px", color: "#8b949e" }}>{a.type}</td>
              <td style={{ padding: "6px 8px", color: "#8b949e" }}>{formatBytes(a.sizeBytes)}</td>
              <td style={{ padding: "6px 8px", color: "#8b949e" }}>
                {new Date(a.createdAt).toLocaleString()}
              </td>
              <td style={{ padding: "6px 8px" }}>
                <a
                  href={downloadArtifactUrl(a.id)}
                  download={a.name}
                  style={{ color: "#58a6ff", textDecoration: "none" }}
                >
                  Download
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
