/**
 * Timeline sub-view — per-session structural changes for multi-session jobs.
 */
import { useEffect, useState } from "react";
import { AlertTriangle, TrendingUp } from "lucide-react";
import { fetchMultiSession, type MultiSessionResponse, type StructuralChange } from "../../api/client";
import { useStore } from "../../store";
import { selectMultiSession } from "../../store/selectors";
import { Spinner } from "../ui/spinner";

interface TimelineSubViewProps {
  jobId: string;
}

const CATEGORY_DOT: Record<string, string> = {
  breaking: "bg-red-400",
  body: "bg-yellow-400",
  additive: "bg-green-400",
  "non-structural": "bg-zinc-400",
};

function SessionCard({ session }: { session: { sessionNumber: number; changes: StructuralChange[]; risk: number; warnings: Array<Record<string, unknown>> } }) {
  const breakingCount = session.changes.filter(c => c.category === "breaking").length;
  const additiveCount = session.changes.filter(c => c.category === "additive").length;
  const bodyCount = session.changes.filter(c => c.category === "body").length;

  return (
    <div className="relative pl-6 pb-6">
      {/* Timeline connector */}
      <div className="absolute left-2 top-3 bottom-0 w-px bg-border" />
      <div className="absolute left-[5px] top-2 w-2.5 h-2.5 rounded-full bg-primary border-2 border-card" />

      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold">Session {session.sessionNumber}</span>
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
            session.risk > 0.6 ? "text-red-400 bg-red-400/10" :
            session.risk > 0.3 ? "text-yellow-400 bg-yellow-400/10" :
            "text-green-400 bg-green-400/10"
          }`}>
            risk {Math.round(session.risk * 100)}%
          </span>
        </div>

        {/* Change summary */}
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground mb-2">
          {breakingCount > 0 && (
            <span className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${CATEGORY_DOT.breaking}`} />
              {breakingCount} breaking
            </span>
          )}
          {bodyCount > 0 && (
            <span className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${CATEGORY_DOT.body}`} />
              {bodyCount} body
            </span>
          )}
          {additiveCount > 0 && (
            <span className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${CATEGORY_DOT.additive}`} />
              {additiveCount} additive
            </span>
          )}
        </div>

        {/* Symbols changed */}
        <div className="flex flex-col gap-0.5">
          {session.changes.slice(0, 5).map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${CATEGORY_DOT[c.category] ?? CATEGORY_DOT["non-structural"]}`} />
              <span className="font-mono text-muted-foreground truncate">{c.symbol ?? c.file}</span>
              <span className="text-[10px] text-muted-foreground ml-auto">{c.kind}</span>
            </div>
          ))}
          {session.changes.length > 5 && (
            <span className="text-[10px] text-muted-foreground pl-4">
              +{session.changes.length - 5} more
            </span>
          )}
        </div>

        {/* Warnings */}
        {session.warnings.length > 0 && (
          <div className="mt-2 flex items-center gap-1 text-[10px] text-yellow-400">
            <AlertTriangle size={10} />
            <span>{session.warnings.length} warning{session.warnings.length !== 1 ? "s" : ""}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function TimelineSubView({ jobId }: TimelineSubViewProps) {
  const cached = useStore(selectMultiSession(jobId));
  const setMultiSession = useStore((s) => s.setMultiSession);

  const [data, setData] = useState<MultiSessionResponse | null>(cached);
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

    fetchMultiSession(jobId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setMultiSession(jobId, res);
        }
      })
      .catch((err) => { if (!cancelled) setError(err?.message ?? "Failed to load session timeline"); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [jobId, cached, setMultiSession]);

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

  if (!data || !data.available || data.sessions.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">
        Multi-session analysis not available.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-4 h-full overflow-y-auto">
      {/* Direction change warnings */}
      {data.directionChanges.length > 0 && (
        <div className="rounded-lg border border-yellow-400/30 bg-yellow-400/5 p-3 mb-2">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp size={14} className="text-yellow-400" />
            <span className="text-xs font-medium text-yellow-400">Direction Changes</span>
          </div>
          <p className="text-[10px] text-muted-foreground">
            {data.directionChanges.length} direction change{data.directionChanges.length !== 1 ? "s" : ""} detected — 
            the agent revised its own earlier work between sessions.
          </p>
        </div>
      )}

      {/* Session timeline */}
      {data.sessions.map((session) => (
        <SessionCard key={session.sessionNumber} session={session} />
      ))}
    </div>
  );
}
