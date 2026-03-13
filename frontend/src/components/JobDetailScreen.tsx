import { useEffect, useState, useCallback, lazy, Suspense } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTowerStore, selectJobs } from "../store";
import type { JobSummary } from "../store";
import { fetchJob, cancelJob, rerunJob } from "../api/client";
import { useSSE } from "../hooks/useSSE";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card, CardContent } from "../ui/Card";
import { Tabs } from "../ui/Tabs";
import { Spinner, EmptyState } from "../ui/Feedback";
import { TranscriptPanel } from "./TranscriptPanel";
import { LogsPanel } from "./LogsPanel";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { ApprovalBanner } from "./ApprovalBanner";
import { OperatorMessageInput } from "./OperatorMessageInput";
import { toast } from "sonner";

const DiffViewer = lazy(() => import("./DiffViewer"));
const WorkspaceBrowser = lazy(() => import("./WorkspaceBrowser"));
const ArtifactViewer = lazy(() => import("./ArtifactViewer"));

type DetailTab = "live" | "diff" | "workspace" | "artifacts";

export function JobDetailScreen() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const jobs = useTowerStore(selectJobs);
  const job: JobSummary | undefined = jobId ? jobs[jobId] : undefined;
  const [loading, setLoading] = useState(!job);
  const [actionLoading, setActionLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>("live");

  useSSE(jobId);

  useEffect(() => {
    if (!jobId) { setLoading(false); return; }
    const existing = useTowerStore.getState().jobs[jobId];
    if (existing) { setLoading(false); return; }
    fetchJob(jobId)
      .then((f) => useTowerStore.setState((s) => ({ jobs: { ...s.jobs, [f.id]: f } })))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [jobId]);

  const handleCancel = useCallback(async () => {
    if (!jobId) return;
    setActionLoading(true);
    try {
      const updated = await cancelJob(jobId);
      useTowerStore.setState((s) => ({ jobs: { ...s.jobs, [updated.id]: updated } }));
      toast.success("Job canceled");
    } catch (e) { toast.error(`Cancel failed: ${e}`); }
    finally { setActionLoading(false); }
  }, [jobId]);

  const handleRerun = useCallback(async () => {
    if (!jobId) return;
    setActionLoading(true);
    try {
      const result = await rerunJob(jobId);
      toast.success(`Rerun created: ${result.id}`);
      navigate(`/jobs/${result.id}`);
    } catch (e) { toast.error(`Rerun failed: ${e}`); }
    finally { setActionLoading(false); }
  }, [jobId, navigate]);

  if (!jobId) return null;
  if (loading) return <Spinner />;
  if (!job) return (
    <div>
      <Button variant="ghost" size="sm" onClick={() => navigate("/")}>← Back</Button>
      <EmptyState text="Job not found" className="mt-8" />
    </div>
  );

  const repoName = job.repo.split("/").pop() ?? job.repo;
  const canCancel = ["queued", "running", "waiting_for_approval"].includes(job.state);
  const canRerun = ["succeeded", "failed", "canceled"].includes(job.state);

  return (
    <div className="max-w-5xl mx-auto">
      <Button variant="ghost" size="sm" onClick={() => navigate("/")} className="mb-4">
        ← Back to Dashboard
      </Button>

      {/* Metadata */}
      <Card className="mb-4">
        <CardContent>
          <div className="flex justify-between items-start flex-wrap gap-2 mb-3">
            <div className="flex items-center gap-2 text-lg font-semibold">
              {job.id} <Badge state={job.state} />
            </div>
            <div className="flex gap-2">
              {canCancel && (
                <Button variant="danger" size="sm" disabled={actionLoading} onClick={handleCancel}>Cancel</Button>
              )}
              {canRerun && (
                <Button size="sm" disabled={actionLoading} onClick={handleRerun}>Rerun</Button>
              )}
            </div>
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-x-6 gap-y-2 text-sm">
            {[
              ["Repository", repoName],
              ["Branch", job.branch ?? "—"],
              ["Base Ref", job.baseRef],
              ["Strategy", job.strategy],
              ["Created", new Date(job.createdAt).toLocaleString()],
              ["Updated", new Date(job.updatedAt).toLocaleString()],
              ...(job.completedAt ? [["Completed", new Date(job.completedAt).toLocaleString()]] : []),
            ].map(([label, value]) => (
              <div key={label}>
                <div className="text-[11px] text-text-dim uppercase tracking-wide">{label}</div>
                <div className="text-text break-all">{value}</div>
              </div>
            ))}
          </div>
          {job.prUrl && (
            <a
              href={job.prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block mt-3 text-sm text-accent hover:underline"
            >
              View Pull Request →
            </a>
          )}
          <div className="mt-3 p-3 bg-bg rounded-md text-sm leading-relaxed whitespace-pre-wrap">{job.prompt}</div>
        </CardContent>
      </Card>

      {/* Tabs */}
      <Tabs
        tabs={[
          { id: "live", label: "Live" },
          { id: "diff", label: "Diff" },
          { id: "workspace", label: "Workspace" },
          { id: "artifacts", label: "Artifacts" },
        ]}
        active={activeTab}
        onChange={(id) => setActiveTab(id as DetailTab)}
        className="mb-4"
      />

      {activeTab === "live" && (
        <div className="space-y-4">
          <ApprovalBanner jobId={jobId} />
          {["running", "waiting_for_approval"].includes(job.state) && (
            <OperatorMessageInput jobId={jobId} />
          )}
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
            <TranscriptPanel jobId={jobId} />
            <LogsPanel jobId={jobId} />
          </div>
          <ExecutionTimeline jobId={jobId} />
        </div>
      )}

      {activeTab === "diff" && (
        <Suspense fallback={<Spinner />}>
          <DiffViewer jobId={jobId} />
        </Suspense>
      )}
      {activeTab === "workspace" && (
        <Suspense fallback={<Spinner />}>
          <WorkspaceBrowser jobId={jobId} />
        </Suspense>
      )}
      {activeTab === "artifacts" && (
        <Suspense fallback={<Spinner />}>
          <ArtifactViewer jobId={jobId} />
        </Suspense>
      )}
    </div>
  );
}
