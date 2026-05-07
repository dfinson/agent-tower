/**
 * Impact Graph Modal — shows the reference/caller graph for a symbol.
 * Opens from a ChangeCard click in the Dashboard sub-view.
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { fetchImpactGraph, type ImpactGraphResponse, type ImpactReference } from "../../api/client";
import { Spinner } from "../ui/spinner";

interface ImpactGraphModalProps {
  jobId: string;
  symbol: string;
  onClose: () => void;
}

const TIER_STYLES: Record<string, string> = {
  verified: "text-green-400 bg-green-400/10 border-green-400/20",
  inferred: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  unverified: "text-red-400 bg-red-400/10 border-red-400/20",
};

function ReferenceRow({ reference: r }: { reference: ImpactReference }) {
  const tierStyle = TIER_STYLES[r.tier] ?? TIER_STYLES.unverified;
  return (
    <div className="flex items-center gap-3 px-3 py-2 hover:bg-accent/30 rounded">
      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${tierStyle}`}>
        {r.tier}
      </span>
      <div className="flex flex-col gap-0.5 flex-1 min-w-0">
        <span className="text-xs font-mono font-medium text-foreground truncate">{r.symbol}</span>
        <span className="text-[10px] text-muted-foreground truncate">
          {r.file}{r.line != null && `:${r.line}`}
        </span>
      </div>
      {r.isTest && (
        <span className="text-[10px] text-green-400 shrink-0">test</span>
      )}
    </div>
  );
}

export function ImpactGraphModal({ jobId, symbol, onClose }: ImpactGraphModalProps) {
  const [data, setData] = useState<ImpactGraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchImpactGraph(jobId, symbol)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((err) => { if (!cancelled) setError(err?.message ?? "Failed to load impact graph"); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [jobId, symbol]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-card border border-border rounded-lg shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex flex-col gap-0.5">
            <h3 className="text-sm font-semibold">Impact Graph</h3>
            <span className="text-xs font-mono text-muted-foreground">{symbol}</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-accent transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex items-center justify-center h-32">
              <Spinner size="md" />
            </div>
          )}

          {error && (
            <div className="text-sm text-muted-foreground text-center py-8">{error}</div>
          )}

          {data && !data.available && (
            <div className="text-sm text-muted-foreground text-center py-8">
              Impact analysis not available.
            </div>
          )}

          {data && data.available && (
            <div className="flex flex-col gap-4">
              {/* Summary stats */}
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span>{data.totalReferences} reference{data.totalReferences !== 1 ? "s" : ""}</span>
                <span>{data.filesAffected} file{data.filesAffected !== 1 ? "s" : ""}</span>
              </div>

              {data.summary && (
                <p className="text-xs text-muted-foreground">{data.summary}</p>
              )}

              {/* Reference list */}
              {data.references.length > 0 ? (
                <div className="flex flex-col gap-0.5">
                  {data.references.map((r, i) => (
                    <ReferenceRow key={`${r.file}-${r.symbol}-${i}`} reference={r} />
                  ))}
                </div>
              ) : (
                <div className="text-xs text-muted-foreground text-center py-4">
                  No references found.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
