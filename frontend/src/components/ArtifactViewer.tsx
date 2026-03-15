import { useEffect, useState } from "react";
import { type LucideIcon, Download, FileText, FileCode } from "lucide-react";
import { fetchArtifacts, downloadArtifactUrl } from "../api/client";
import { Badge } from "./ui/badge";
import { Spinner } from "./ui/spinner";

interface Artifact {
  id: string;
  jobId: string;
  name: string;
  type: string;
  mimeType: string;
  sizeBytes: number;
  phase: string;
  createdAt: string;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  diff_snapshot: FileCode,
  custom: FileText,
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props { jobId: string; }

export default function ArtifactViewer({ jobId }: Props) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchArtifacts(jobId)
      .then((res) => setArtifacts(res.items as Artifact[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [jobId]);

  if (loading) return <div className="flex justify-center py-10"><Spinner /></div>;

  if (artifacts.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        <p className="text-sm text-muted-foreground">No artifacts available</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Name</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground hidden sm:table-cell">Type</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Size</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground hidden sm:table-cell">Created</th>
              <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground" />
            </tr>
          </thead>
          <tbody>
            {artifacts.map((a) => {
              const Icon = TYPE_ICON[a.type] ?? FileText;
              return (
                <tr key={a.id} className="border-b border-border/50 hover:bg-accent/30">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <Icon size={14} className="text-muted-foreground shrink-0" />
                      <span className="truncate">{a.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 hidden sm:table-cell">
                    <Badge variant="secondary">{a.type}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-muted-foreground">{formatSize(a.sizeBytes)}</td>
                  <td className="px-4 py-2.5 text-muted-foreground text-xs hidden sm:table-cell">{new Date(a.createdAt).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right">
                    <a
                      href={downloadArtifactUrl(a.id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center w-8 h-8 text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <Download size={14} />
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
