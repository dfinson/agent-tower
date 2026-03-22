/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useStore } from "../../store";
import type { JobSummary } from "../../store";

vi.mock("../../api/client", () => ({
  fetchJob: vi.fn(),
  cancelJob: vi.fn(),
  rerunJob: vi.fn(),
  fetchJobTranscript: vi.fn().mockResolvedValue([]),
  fetchJobTimeline: vi.fn().mockResolvedValue([]),
  fetchJobDiff: vi.fn().mockResolvedValue([]),
  fetchApprovals: vi.fn().mockResolvedValue([]),
  resolveJob: vi.fn(),
  fetchArtifacts: vi.fn().mockResolvedValue({ items: [] }),
  createTerminalSession: vi.fn(),
}));

vi.mock("../../hooks/useSSE", () => ({
  useSSE: () => ({ reconnect: vi.fn() }),
}));

vi.mock("../../hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../TranscriptPanel", () => ({
  TranscriptPanel: () => <div data-testid="transcript-panel" />,
}));

vi.mock("../MetricsPanel", () => ({
  MetricsPanel: () => <div data-testid="metrics-panel" />,
}));

vi.mock("../ExecutionTimeline", () => ({
  ExecutionTimeline: () => <div data-testid="timeline-panel" />,
}));

vi.mock("../PlanPanel", () => ({
  PlanPanel: () => <div data-testid="plan-panel" />,
}));

vi.mock("../CompleteJobDialog", () => ({
  CompleteJobDialog: () => null,
}));

vi.mock("../StateBadge", () => ({
  StateBadge: ({ state }: { state: string }) => <span>{state}</span>,
}));

vi.mock("../SdkBadge", () => ({
  SdkBadge: () => <span>sdk</span>,
}));

vi.mock("../ui/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../ui/confirm-dialog", () => ({
  ConfirmDialog: () => null,
}));

import { fetchJob } from "../../api/client";
import { JobDetailScreen } from "../JobDetailScreen";

function makeJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-1",
    repo: "/repos/test",
    prompt: "Fix the bug",
    title: "Fix bug",
    state: "succeeded",
    baseRef: "main",
    worktreePath: "/repos/test/.cpl-worktrees/job-1",
    branch: "fix/bug",
    createdAt: "2025-01-01T00:00:00Z",
    updatedAt: "2025-01-01T00:00:00Z",
    completedAt: "2025-01-01T01:00:00Z",
    prUrl: null,
    resolution: "conflict",
    mergeStatus: "conflict",
    archivedAt: null,
    sdk: "copilot",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchJob).mockReset();
  useStore.setState({
    jobs: {},
    approvals: {},
    logs: {},
    transcript: {},
    diffs: {},
    timelines: {},
    plans: {},
    telemetryVersions: {},
    terminalSessions: {},
    activeTerminalTab: null,
    terminalDrawerOpen: false,
    terminalDrawerHeight: 320,
    connectionStatus: "connected",
    reconnectAttempt: 0,
  } as any);

  class ResizeObserverMock {
    observe() {}
    disconnect() {}
    unobserve() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverMock);
});

describe("JobDetailScreen", () => {
  it("re-fetches the job even when a cached copy already exists", async () => {
    useStore.setState({
      jobs: {
        "job-1": makeJob({ resolution: "conflict", updatedAt: "2025-01-01T00:00:00Z" }),
      },
    });

    vi.mocked(fetchJob).mockResolvedValueOnce(
      makeJob({ resolution: "unresolved", mergeStatus: "not_merged", updatedAt: "2025-01-01T02:00:00Z" }) as any,
    );

    render(
      <MemoryRouter initialEntries={["/jobs/job-1"]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetailScreen />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(fetchJob).toHaveBeenCalledWith("job-1");
    });

    await waitFor(() => {
      expect(useStore.getState().jobs["job-1"]?.resolution).toBe("unresolved");
      expect(useStore.getState().jobs["job-1"]?.mergeStatus).toBe("not_merged");
    });
  });

  it("keeps the live transcript area on screen in desktop job views", async () => {
    useStore.setState({
      jobs: {
        "job-1": makeJob({ state: "running", resolution: null }),
      },
    });

    vi.mocked(fetchJob).mockResolvedValueOnce(makeJob({ state: "running", resolution: null }) as any);

    render(
      <MemoryRouter initialEntries={["/jobs/job-1"]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetailScreen />} />
        </Routes>
      </MemoryRouter>,
    );

    const transcriptPanel = await screen.findByTestId("transcript-panel");
    expect(transcriptPanel.parentElement).toHaveClass("flex-1", "min-h-[22rem]");
    expect(transcriptPanel.parentElement?.parentElement).toHaveClass("md:h-[calc(100vh-15rem)]", "md:min-h-[42rem]");
  });
});