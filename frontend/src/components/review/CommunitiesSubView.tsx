/**
 * CommunitiesSubView — shows structural changes grouped by module community.
 *
 * Each community is a cluster of related symbols (same module/package boundary).
 * Displays total risk per community, with expandable change lists.
 */
import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Network } from "lucide-react";
import { fetchCommunities, type CommunitiesResponse, type CommunityGroup } from "../../api/client";
import { useStore } from "../../store";
import { selectCommunities } from "../../store/selectors";
import { Spinner } from "../ui/spinner";

interface CommunitiesSubViewProps {
  jobId: string;
}

function CommunityCard({ community }: { community: CommunityGroup }) {
  const [expanded, setExpanded] = useState(false);
  const riskPct = Math.round(community.totalRisk * 100);
  const riskColor = riskPct > 70 ? "text-red-400" : riskPct > 40 ? "text-yellow-400" : "text-green-400";

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-accent/30 transition-colors"
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Network size={14} className="text-muted-foreground" />
        <span className="text-sm font-medium text-foreground flex-1 text-left">{community.name}</span>
        <span className="text-xs text-muted-foreground">
          {community.changes.length} change{community.changes.length !== 1 ? "s" : ""}
        </span>
        <span className={`text-xs font-medium ${riskColor}`}>
          {riskPct}% risk
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border divide-y divide-border">
          {community.changes.map((change, i) => {
            const symbol = change.symbol as string | undefined;
            const file = change.file as string | undefined;
            const risk = change.risk as number | undefined;
            const category = change.category as string | undefined;
            return (
              <div key={i} className="flex items-center gap-3 px-4 py-2 pl-10">
                <span className="text-xs font-mono text-muted-foreground truncate flex-1">
                  {symbol || file || "unknown"}
                </span>
                {category && (
                  <span className="text-[10px] uppercase text-muted-foreground">{category}</span>
                )}
                {risk != null && (
                  <span className="text-[10px] text-muted-foreground">
                    {Math.round(risk * 100)}%
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function CommunitiesSubView({ jobId }: CommunitiesSubViewProps) {
  const cached = useStore(selectCommunities(jobId));
  const setCommunities = useStore((s) => s.setCommunities);

  const [data, setData] = useState<CommunitiesResponse | null>(cached);
  const [loading, setLoading] = useState(cached == null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cached != null) {
      setData(cached);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchCommunities(jobId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setCommunities(jobId, res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? "Failed to load communities");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [jobId, cached, setCommunities]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Spinner size="md" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        {error}
      </div>
    );
  }

  if (!data || !data.available || data.communities.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        No community clusters detected.
      </div>
    );
  }

  // Sort communities by total risk descending
  const sorted = [...data.communities].sort((a, b) => b.totalRisk - a.totalRisk);

  return (
    <div className="flex flex-col gap-3 p-4 h-full overflow-y-auto">
      <div className="flex items-center gap-2 mb-1">
        <h3 className="text-sm font-semibold">Module Communities</h3>
        <span className="text-xs text-muted-foreground">
          {sorted.length} cluster{sorted.length !== 1 ? "s" : ""}
        </span>
      </div>

      {sorted.map((community) => (
        <CommunityCard key={community.name} community={community} />
      ))}

      {data.unclustered.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h4 className="text-xs font-medium text-muted-foreground mb-2">
            Unclustered ({data.unclustered.length})
          </h4>
          <div className="flex flex-col gap-1">
            {data.unclustered.map((item, i) => (
              <span key={i} className="text-xs font-mono text-muted-foreground">
                {(item.symbol as string) || (item.file as string) || JSON.stringify(item)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
