import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRightLeft, Plus, Minus, Pencil } from "lucide-react";
import { fetchStructuralDiff, type StructuralChange, type StructuralDiffResponse } from "../api/client";
import { Spinner } from "./ui/spinner";

const KIND_ICONS: Record<string, typeof Plus> = {
  added: Plus,
  removed: Minus,
  modified: Pencil,
  moved: ArrowRightLeft,
};

const KIND_COLORS: Record<string, string> = {
  added: "text-green-400",
  removed: "text-red-400",
  modified: "text-yellow-400",
  moved: "text-blue-400",
};

function ChangeRow({ change }: { change: StructuralChange }) {
  const Icon = KIND_ICONS[change.kind] ?? Pencil;
  const color = KIND_COLORS[change.kind] ?? "text-muted-foreground";

  return (
    <div className="flex items-start gap-3 px-3 py-2 rounded-md hover:bg-accent/50 transition-colors">
      <Icon size={14} className={`shrink-0 mt-0.5 ${color}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-muted-foreground truncate">{change.file}</span>
          {change.symbol && (
            <span className="text-xs font-semibold text-foreground">{change.symbol}</span>
          )}
        </div>
        {change.summary && (
          <p className="text-xs text-muted-foreground mt-0.5">{change.summary}</p>
        )}
      </div>
      <span className={`text-[10px] uppercase font-medium ${color}`}>{change.kind}</span>
    </div>
  );
}

export function ReviewDashboard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<StructuralDiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchStructuralDiff(jobId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? "Failed to load structural diff");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [jobId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 justify-center h-48 text-sm text-muted-foreground">
        <AlertTriangle size={16} className="text-yellow-400" />
        <span>{error}</span>
      </div>
    );
  }

  if (!data || !data.available) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        Structural analysis not available for this job.
      </div>
    );
  }

  if (data.changes.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        No structural changes detected.
      </div>
    );
  }

  // Group by kind for summary counts
  const counts = data.changes.reduce<Record<string, number>>((acc, c) => {
    acc[c.kind] = (acc[c.kind] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-4 p-4 h-full overflow-y-auto">
      {/* Summary header */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-semibold mb-2">Structural Summary</h3>
        <p className="text-xs text-muted-foreground mb-3">{data.summary}</p>
        <div className="flex gap-3 flex-wrap">
          {Object.entries(counts).map(([kind, count]) => {
            const color = KIND_COLORS[kind] ?? "text-muted-foreground";
            return (
              <span key={kind} className={`text-xs font-medium ${color}`}>
                {count} {kind}
              </span>
            );
          })}
        </div>
      </div>

      {/* Change list */}
      <div className="rounded-lg border border-border bg-card">
        <div className="px-3 py-2 border-b border-border">
          <span className="text-xs font-medium text-muted-foreground">
            {data.changes.length} structural change{data.changes.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="divide-y divide-border">
          {data.changes.map((change, i) => (
            <ChangeRow key={`${change.file}-${change.symbol}-${i}`} change={change} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default ReviewDashboard;
