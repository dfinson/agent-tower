import { useEffect, useState, useCallback, lazy, Suspense } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Paper, Group, Text, Button, Tabs, Anchor, Loader, Stack,
} from "@mantine/core";
import {
  ArrowLeft, RotateCcw, XCircle, ExternalLink,
} from "lucide-react";
import { notifications } from "@mantine/notifications";
import { useTowerStore, selectJobs } from "../store";
import type { JobSummary } from "../store";
import { fetchJob, cancelJob, rerunJob } from "../api/client";
import { useSSE } from "../hooks/useSSE";
import { StateBadge } from "./StateBadge";
import { TranscriptPanel } from "./TranscriptPanel";
import { LogsPanel } from "./LogsPanel";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { ApprovalBanner } from "./ApprovalBanner";
import { TelemetryPanel } from "./TelemetryPanel";

const DiffViewer = lazy(() => import("./DiffViewer"));
const WorkspaceBrowser = lazy(() => import("./WorkspaceBrowser"));
const ArtifactViewer = lazy(() => import("./ArtifactViewer"));

export function JobDetailScreen() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const jobs = useTowerStore(selectJobs);
  const job: JobSummary | undefined = jobId ? jobs[jobId] : undefined;
  const [loading, setLoading] = useState(!job);
  const [actionLoading, setActionLoading] = useState(false);
  const [tab, setTab] = useState<string | null>("live");

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
      notifications.show({ color: "green", message: "Job canceled" });
    } catch (e) { notifications.show({ color: "red", message: String(e) }); }
    finally { setActionLoading(false); }
  }, [jobId]);

  const handleRerun = useCallback(async () => {
    if (!jobId) return;
    setActionLoading(true);
    try {
      const result = await rerunJob(jobId);
      notifications.show({ color: "green", message: `Rerun: ${result.id}` });
      navigate(`/jobs/${result.id}`);
    } catch (e) { notifications.show({ color: "red", message: String(e) }); }
    finally { setActionLoading(false); }
  }, [jobId, navigate]);

  if (!jobId) return null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader size="lg" />
      </div>
    );
  }

  if (!job) {
    return (
      <Stack align="center" py="xl" gap="md">
        <Text size="lg" c="dimmed">Job not found</Text>
        <Button variant="subtle" leftSection={<ArrowLeft size={16} />} onClick={() => navigate("/")}>
          Back to Dashboard
        </Button>
      </Stack>
    );
  }

  const repoName = job.repo.split("/").pop() ?? job.repo;
  const canCancel = ["queued", "running", "waiting_for_approval"].includes(job.state);
  const canRerun = ["succeeded", "failed", "canceled"].includes(job.state);
  const isInteractive = ["running", "waiting_for_approval"].includes(job.state);

  return (
    <div className="max-w-6xl mx-auto">
      {/* Back button */}
      <Button
        variant="subtle"
        size="xs"
        leftSection={<ArrowLeft size={14} />}
        onClick={() => navigate("/")}
        mb="md"
      >
        Dashboard
      </Button>

      {/* Job header */}
      <Paper radius="lg" p="md" mb="md">
        <Group justify="space-between" wrap="wrap" mb="sm">
          <Group gap="sm">
            <Text size="lg" fw={700}>{job.id}</Text>
            <StateBadge state={job.state} />
          </Group>
          <Group gap="xs">
            {canCancel && (
              <Button
                size="xs"
                color="red"
                variant="light"
                leftSection={<XCircle size={14} />}
                loading={actionLoading}
                onClick={handleCancel}
              >
                Cancel
              </Button>
            )}
            {canRerun && (
              <Button
                size="xs"
                variant="light"
                leftSection={<RotateCcw size={14} />}
                loading={actionLoading}
                onClick={handleRerun}
              >
                Rerun
              </Button>
            )}
          </Group>
        </Group>

        {/* Metadata grid */}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-6 gap-y-2 text-sm mb-3">
          {[
            ["Repo", repoName],
            ["Branch", job.branch ?? "—"],
            ["Base", job.baseRef],
            ["Strategy", job.strategy],
            ["Created", new Date(job.createdAt).toLocaleString()],
            ...(job.completedAt ? [["Completed", new Date(job.completedAt).toLocaleString()]] : []),
          ].map(([label, value]) => (
            <div key={label}>
              <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
              <Text size="sm" className="break-all">{value}</Text>
            </div>
          ))}
        </div>

        {job.prUrl && (
          <Anchor href={job.prUrl} target="_blank" size="sm">
            <Group gap={4}><ExternalLink size={14} /> View Pull Request</Group>
          </Anchor>
        )}

        {/* Prompt */}
        <Paper bg="dark.8" p="sm" radius="md" mt="sm">
          <Text size="sm" className="whitespace-pre-wrap leading-relaxed">{job.prompt}</Text>
        </Paper>
      </Paper>

      {/* Tabs */}
      <Tabs value={tab} onChange={setTab} mb="md">
        <Tabs.List>
          <Tabs.Tab value="live">Live</Tabs.Tab>
          <Tabs.Tab value="diff">Diff</Tabs.Tab>
          <Tabs.Tab value="workspace">Workspace</Tabs.Tab>
          <Tabs.Tab value="artifacts">Artifacts</Tabs.Tab>
        </Tabs.List>
      </Tabs>

      {/* Tab content */}
      {tab === "live" && (
        <Stack gap="md">
          <ApprovalBanner jobId={jobId} />
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1" style={{ minHeight: 400 }}>
            <TranscriptPanel jobId={jobId} interactive={isInteractive} />
            <LogsPanel jobId={jobId} />
          </div>
          <ExecutionTimeline jobId={jobId} />
          <TelemetryPanel jobId={jobId} />
        </Stack>
      )}

      {tab === "diff" && (
        <Suspense fallback={<div className="flex justify-center py-10"><Loader /></div>}>
          <DiffViewer jobId={jobId} />
        </Suspense>
      )}

      {tab === "workspace" && (
        <Suspense fallback={<div className="flex justify-center py-10"><Loader /></div>}>
          <WorkspaceBrowser jobId={jobId} />
        </Suspense>
      )}

      {tab === "artifacts" && (
        <Suspense fallback={<div className="flex justify-center py-10"><Loader /></div>}>
          <ArtifactViewer jobId={jobId} />
        </Suspense>
      )}
    </div>
  );
}
