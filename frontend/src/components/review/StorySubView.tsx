/**
 * Story sub-view — structured review story with header, attention items,
 * concerns, and verdict. Falls back to trail-based narrative when
 * structural enrichment is unavailable.
 */
import { useEffect, useState } from "react";
import { AlertTriangle, ShieldAlert, ShieldCheck, Shield, CheckCircle, XCircle } from "lucide-react";
import { fetchReviewStory, type ReviewStoryResponse } from "../../api/client";
import { Spinner } from "../ui/spinner";

interface StorySubViewProps {
  jobId: string;
}

const CONFIDENCE_CONFIG: Record<string, { icon: typeof ShieldCheck; color: string; label: string }> = {
  HIGH: { icon: ShieldCheck, color: "text-green-400", label: "High Confidence" },
  MEDIUM: { icon: Shield, color: "text-yellow-400", label: "Medium Confidence" },
  LOW: { icon: ShieldAlert, color: "text-red-400", label: "Low Confidence" },
};

function StorySection({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{title}</h4>
      <div className="flex flex-col gap-1.5">
        {items.map((item, i) => (
          <div key={i} className="text-xs text-foreground/90 pl-3 border-l-2 border-border py-1">
            {item.symbol ? (
              <span className="font-mono font-medium">{String(item.symbol)}</span>
            ) : null}
            {item.summary ? (
              <span className="text-muted-foreground"> &mdash; {String(item.summary)}</span>
            ) : item.detail ? (
              <span className="text-muted-foreground">{String(item.detail)}</span>
            ) : (
              <span className="text-muted-foreground">{JSON.stringify(item)}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function StorySubView({ jobId }: StorySubViewProps) {
  const [data, setData] = useState<ReviewStoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchReviewStory(jobId)
      .then((res) => { if (!cancelled) setData(res); })
      .catch((err) => { if (!cancelled) setError(err?.message ?? "Failed to load review story"); })
      .finally(() => { if (!cancelled) setLoading(false); });

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
        Review story not available for this job.
      </div>
    );
  }

  const confidenceCfg = data.header?.mergeConfidence
    ? CONFIDENCE_CONFIG[data.header.mergeConfidence]
    : null;

  return (
    <div className="flex flex-col gap-5 p-4 h-full overflow-y-auto">
      {/* Header card */}
      {data.header && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold">
              {data.header.title || "Review Story"}
            </h3>
            {confidenceCfg && (
              <div className={`flex items-center gap-1.5 text-xs font-medium ${confidenceCfg.color}`}>
                <confidenceCfg.icon size={14} />
                <span>{confidenceCfg.label}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
            <span>{data.header.fileCount} file{data.header.fileCount !== 1 ? "s" : ""} changed</span>
            {data.header.breakingCount > 0 && (
              <span className="text-red-400">{data.header.breakingCount} breaking</span>
            )}
          </div>
        </div>
      )}

      {/* Attention required */}
      <StorySection title="Needs Attention" items={data.attentionRequired} />

      {/* Structural concerns */}
      <StorySection title="Structural Concerns" items={data.structuralConcerns} />

      {/* What changed */}
      <StorySection title="What Changed" items={data.whatChanged} />

      {/* What was added */}
      <StorySection title="What Was Added" items={data.whatAdded} />

      {/* Non-structural count */}
      {data.nonStructuralCount > 0 && (
        <div className="text-xs text-muted-foreground">
          +{data.nonStructuralCount} non-structural change{data.nonStructuralCount !== 1 ? "s" : ""} (formatting, comments, etc.)
        </div>
      )}

      {/* Verdict */}
      {data.verdict && (
        <div className={`rounded-lg border p-4 ${
          data.verdict.confidence === "HIGH" ? "border-green-400/30 bg-green-400/5" :
          data.verdict.confidence === "LOW" ? "border-red-400/30 bg-red-400/5" :
          "border-yellow-400/30 bg-yellow-400/5"
        }`}>
          <div className="flex items-center gap-2 mb-2">
            {data.verdict.confidence === "HIGH" ? (
              <CheckCircle size={14} className="text-green-400" />
            ) : data.verdict.confidence === "LOW" ? (
              <XCircle size={14} className="text-red-400" />
            ) : (
              <AlertTriangle size={14} className="text-yellow-400" />
            )}
            <span className="text-xs font-semibold">Verdict</span>
          </div>

          {data.verdict.summary && (
            <p className="text-xs text-foreground/90 mb-2">{data.verdict.summary}</p>
          )}

          {data.verdict.blockers.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-[10px] font-medium text-muted-foreground uppercase">Blockers</span>
              {data.verdict.blockers.map((b, i) => (
                <div key={i} className="text-xs text-red-400 pl-2 border-l-2 border-red-400/30">
                  {b}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
