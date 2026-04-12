/**
 * Read-only shared job view — accessed via /shared/:token.
 *
 * Fetches job data through the share token endpoints and displays a
 * minimal, non-interactive view of the job status, logs, and diff.
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams } from "react-router-dom";
import type { Job } from "../api/types";
import { StateBadge } from "./StateBadge";
import { Spinner } from "./ui/spinner";

/** Extended job with fields populated from SSE events. */
interface SharedJob extends Job {
  progressHeadline?: string | null;
  description?: string | null;
}

const BASE = "/api";

export function SharedJobView() {
  const { token } = useParams<{ token: string }>();
  const [job, setJob] = useState<SharedJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Fetch job data
  useEffect(() => {
    if (!token) return;
    fetch(`${BASE}/share/${token}/job`)
      .then((r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "Share link expired or invalid" : "Failed to load job");
        return r.json();
      })
      .then(setJob)
      .catch((e) => setError(e.message));
  }, [token]);

  // SSE event stream
  useEffect(() => {
    if (!token || !job) return;
    const es = new EventSource(`${BASE}/share/${token}/events`);

    es.addEventListener("job_state_changed", (e) => {
      try {
        const data = JSON.parse(e.data);
        setJob((prev) => prev ? { ...prev, state: data.new_state ?? data.state ?? prev.state } : prev);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener("log_line_emitted", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.message) {
          setLogs((prev) => [...prev.slice(-999), data.message]);
        }
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener("progress_headline", (e) => {
      try {
        const data = JSON.parse(e.data);
        setJob((prev) => prev ? { ...prev, progressHeadline: data.headline } : prev);
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener("job_completed", () => {
      setJob((prev) => prev ? { ...prev, state: "completed" } : prev);
    });

    es.addEventListener("job_failed", (e) => {
      try {
        const data = JSON.parse(e.data);
        setJob((prev) => prev ? { ...prev, state: "failed", failureReason: data.reason } : prev);
      } catch { /* ignore parse errors */ }
    });

    return () => es.close();
  }, [token, job?.id]);

  // Auto-scroll logs
  const scrollToBottom = useCallback(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [logs, scrollToBottom]);

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-20 text-center">
        <h1 className="text-xl font-bold text-destructive mb-2">Share link unavailable</h1>
        <p className="text-muted-foreground">{error}</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <nav aria-label="Breadcrumb" className="mb-2">
        <ol className="flex items-center gap-2 text-xs sm:text-xs text-sm text-muted-foreground">
          <li>CodePlane</li>
          <li aria-hidden="true" className="text-muted-foreground/50">/</li>
          <li aria-current="page">Shared View</li>
        </ol>
      </nav>

      <main>
      {/* Job header */}
      <div className="rounded-lg border border-border bg-card p-5 mb-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <h1 className="text-lg font-bold text-foreground break-words">
            {job.title || job.id}
          </h1>
          <span aria-live="polite"><StateBadge state={job.state} /></span>
        </div>

        {job.progressHeadline && ["running", "agent_running", "queued"].includes(job.state) && (
          <p className="text-sm italic text-primary/70 mb-3">{job.progressHeadline}</p>
        )}

        {(job.description || job.prompt) && (
          <p className="text-sm text-muted-foreground mb-3">{job.description ?? job.prompt}</p>
        )}

        <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-x-6 gap-y-2 text-sm">
          {[
            ["Branch", job.branch ?? "\u2014"],
            ["Base", job.baseRef],
            ...(job.model ? [["Model", job.model]] : []),
            ["Created", new Date(job.createdAt).toLocaleString()],
            ...(job.completedAt ? [["Completed", new Date(job.completedAt).toLocaleString()]] : []),
          ].map(([label, value]) => (
            <div key={label}>
              <p className="text-[11px] sm:text-xs text-muted-foreground uppercase font-semibold tracking-wide">{label}</p>
              <p className="text-sm break-all">{value}</p>
            </div>
          ))}
        </div>

        {job.failureReason && (
          <div className="mt-3 rounded-md bg-destructive/10 border border-destructive/20 px-3 py-2">
            <p className="text-sm text-destructive">{job.failureReason}</p>
          </div>
        )}
      </div>

      {/* Live logs */}
      {logs.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="text-sm font-semibold mb-3">Live Logs</h2>
          <div className="bg-background rounded-md p-3 max-h-96 overflow-y-auto font-mono text-[13px] sm:text-xs leading-relaxed">
            {logs.map((line, i) => (
              <div key={`log-${i}`} className="text-muted-foreground whitespace-pre-wrap">{line}</div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}
      </main>
    </div>
  );
}
