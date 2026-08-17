/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useStore } from "../../store";
import type { JobSummary } from "../../store";

// Mock the API client
vi.mock("../../api/client", () => ({
  fetchJobs: vi.fn(),
  fetchProject: vi.fn(),
  fetchProjectTaskLinks: vi.fn(),
}));

import { fetchJobs, fetchProject, fetchProjectTaskLinks } from "../../api/client";
import { RepoBoard } from "../RepoBoard";

vi.mock("../KanbanSkeleton", () => ({
  KanbanSkeleton: () => <div data-testid="kanban-skeleton">KanbanSkeleton</div>,
}));

function makeJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-1",
    repo: "/repos/test",
    prompt: "Fix the bug",
    state: "running",
    baseRef: "main",
    worktreePath: "/repos/test",
    branch: "fix/bug",
    createdAt: "2025-01-01T00:00:00Z",
    updatedAt: "2025-01-01T00:00:00Z",
    completedAt: null,
    prUrl: null,
    ...overrides,
  };
}

function makeTaskLink(overrides: Partial<any> = {}) {
  return {
    id: "tl-1",
    projectId: "proj-1",
    repoPath: "/repos/test",
    storyNodeId: "add-sca",
    dependsOn: [],
    jobId: null,
    trackerTicketRef: null,
    promptOverride: null,
    epicId: null,
    createdAt: "2025-01-01T00:00:00Z",
    updatedAt: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeProject(overrides: Partial<any> = {}) {
  return {
    id: "proj-1",
    name: "payments",
    repoPaths: ["/repos/test"],
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}

function renderBoard(projectId = "proj-1") {
  return render(
    <MemoryRouter initialEntries={[`/projects/id/${encodeURIComponent(projectId)}/board`]}>
      <Routes>
        <Route path="/projects/id/:projectId/board" element={<RepoBoard />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(fetchJobs).mockReset();
  vi.mocked(fetchProject).mockReset();
  vi.mocked(fetchProjectTaskLinks).mockReset();
  vi.mocked(fetchProject).mockResolvedValue(makeProject() as any);
  vi.mocked(fetchProjectTaskLinks).mockResolvedValue({ items: [] } as any);
  useStore.setState({
    jobs: {},
    approvals: {},
    logs: {},
    transcript: {},
    diffs: {},
  });
});

describe("RepoBoard", () => {
  it("shows the skeleton immediately on a cold load before jobs arrive", () => {
    vi.mocked(fetchJobs).mockReturnValueOnce(new Promise(() => {}) as any);
    renderBoard();
    expect(screen.getByTestId("kanban-skeleton")).toBeInTheDocument();
  });

  it("keeps the existing board visible during a refresh when jobs are already loaded", () => {
    useStore.setState({
      jobs: { existing: makeJob({ id: "existing" }) },
    });
    vi.mocked(fetchJobs).mockReturnValueOnce(new Promise(() => {}) as any);
    renderBoard();
    expect(screen.queryByTestId("kanban-skeleton")).not.toBeInTheDocument();
  });

  it("fetches jobs on mount", async () => {
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    renderBoard();
    await waitFor(() => {
      expect(fetchJobs).toHaveBeenCalledWith({ limit: 100, archived: false });
    });
  });

  it("renders the Board heading and Project name", async () => {
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    vi.mocked(fetchProject).mockResolvedValueOnce(makeProject({ name: "my-app" }) as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("Board")).toBeInTheDocument());
    expect(screen.getByText("my-app")).toBeInTheDocument();
  });

  it("shows only jobs belonging to the Project's member repos, excluding other repos", async () => {
    const jobA = makeJob({ id: "job-a", repo: "/repos/test", title: "Job A", state: "running" });
    const jobB = makeJob({ id: "job-b", repo: "/repos/other", title: "Job B", state: "running" });
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [jobA, jobB], cursor: null } as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("Job A")).toBeInTheDocument());
    // Job B belongs to a repo outside this Project's membership and must never appear (CAP-1).
    expect(screen.queryByText("Job B")).not.toBeInTheDocument();
  });

  it("aggregates jobs across ALL member repos for a multi-repo Project", async () => {
    vi.mocked(fetchProject).mockResolvedValueOnce(makeProject({ repoPaths: ["/repos/test", "/repos/other"] }) as any);
    const jobA = makeJob({ id: "job-a", repo: "/repos/test", title: "Job A", state: "running" });
    const jobB = makeJob({ id: "job-b", repo: "/repos/other", title: "Job B", state: "running" });
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [jobA, jobB], cursor: null } as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("Job A")).toBeInTheDocument());
    expect(screen.getByText("Job B")).toBeInTheDocument();
  });

  it("classifies scoped jobs into the same three-column buckets as the flat board", async () => {
    const active = makeJob({ id: "active", repo: "/repos/test", title: "Active job", state: "running" });
    const signoff = makeJob({ id: "signoff", repo: "/repos/test", title: "Signoff job", state: "waiting_for_approval" });
    const failed = makeJob({ id: "failed", repo: "/repos/test", title: "Failed job", state: "failed" });
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [active, signoff, failed], cursor: null } as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("Active job")).toBeInTheDocument());
    expect(screen.getByText("Signoff job")).toBeInTheDocument();
    expect(screen.getByText("Failed job")).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
    expect(screen.getByText("Awaiting Input")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Failed" })).toBeInTheDocument();
  });

  it("renders TaskLink cards for the Project in the In Progress column", async () => {
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    vi.mocked(fetchProjectTaskLinks).mockResolvedValueOnce({
      items: [makeTaskLink({ id: "tl-1", storyNodeId: "add-sca" })],
    } as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("add-sca")).toBeInTheDocument());
    expect(screen.getByText("deps satisfied")).toBeInTheDocument();
  });

  it("greys out a TaskLink card whose dependency's linked job has not completed", async () => {
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    vi.mocked(fetchProjectTaskLinks).mockResolvedValueOnce({
      items: [
        makeTaskLink({ id: "tl-1", storyNodeId: "add-sca", jobId: "job-running" }),
        makeTaskLink({ id: "tl-2", storyNodeId: "sca-tests", dependsOn: ["/repos/test::add-sca"] }),
      ],
    } as any);
    useStore.setState({
      jobs: { "job-running": makeJob({ id: "job-running", state: "running" }) },
    });
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("sca-tests")).toBeInTheDocument());
    expect(screen.getByText("waiting on add-sca")).toBeInTheDocument();
    expect(screen.getByLabelText(/waiting on dependencies/)).toHaveClass("opacity-60");
  });

  it("renders a TaskLink card as satisfied once its dependency's job has completed", async () => {
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    vi.mocked(fetchProjectTaskLinks).mockResolvedValueOnce({
      items: [
        makeTaskLink({ id: "tl-1", storyNodeId: "add-sca", jobId: "job-done" }),
        makeTaskLink({ id: "tl-2", storyNodeId: "sca-tests", dependsOn: ["/repos/test::add-sca"] }),
      ],
    } as any);
    useStore.setState({
      jobs: { "job-done": makeJob({ id: "job-done", state: "completed" }) },
    });
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("sca-tests")).toBeInTheDocument());
    expect(screen.getAllByText("deps satisfied")).toHaveLength(2);
  });

  it("renders TaskLink cards from any of the Project's member repos", async () => {
    vi.mocked(fetchProject).mockResolvedValueOnce(makeProject({ repoPaths: ["/repos/test", "/repos/other"] }) as any);
    vi.mocked(fetchJobs).mockResolvedValueOnce({ items: [], cursor: null } as any);
    vi.mocked(fetchProjectTaskLinks).mockResolvedValueOnce({
      items: [
        makeTaskLink({ id: "tl-1", repoPath: "/repos/test", storyNodeId: "add-sca" }),
        makeTaskLink({ id: "tl-2", repoPath: "/repos/other", storyNodeId: "other-task" }),
      ],
    } as any);
    renderBoard("proj-1");
    await waitFor(() => expect(screen.getByText("add-sca")).toBeInTheDocument());
    expect(screen.getByText("other-task")).toBeInTheDocument();
  });
});
