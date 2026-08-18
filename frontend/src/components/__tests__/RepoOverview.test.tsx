/* eslint-disable @typescript-eslint/no-explicit-any */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api/client", () => ({
  fetchProject: vi.fn(),
  fetchRepoSummary: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

import { fetchProject, fetchRepoSummary } from "../../api/client";
import { RepoOverview } from "../RepoOverview";

function summary(path: string, cost: number, jobs: number) {
  return {
    path,
    originUrl: null,
    baseBranch: "main",
    currentBranch: "main",
    platform: "github",
    recentJobs: [],
    activeJobCount: jobs,
    cost: { totalCostUsd: cost, totalJobs: jobs, totalTokens: jobs * 100 },
    health: {
      repo: path,
      available: true,
      indexStatus: "ready",
      symbolCount: 10,
      fileCount: 5,
      lastIndexedSha: "abc",
      communityCount: 2,
      cycleCount: 0,
      stale: false,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchProject).mockResolvedValue({
    id: "project-1",
    name: "Payments",
    repoPaths: ["/repo/api", "/repo/web"],
  } as any);
  vi.mocked(fetchRepoSummary)
    .mockResolvedValueOnce(summary("/repo/api", 1, 1) as any)
    .mockResolvedValueOnce(summary("/repo/web", 2, 2) as any);
});

describe("RepoOverview", () => {
  it("aggregates every member repository without linking to the first implicitly", async () => {
    render(
      <MemoryRouter initialEntries={["/projects/id/project-1"]}>
        <Routes>
          <Route path="/projects/id/:projectId" element={<RepoOverview />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("$3.00")).toBeInTheDocument();
    expect(fetchRepoSummary).toHaveBeenCalledTimes(2);
    expect(fetchRepoSummary).toHaveBeenNthCalledWith(1, "/repo/api");
    expect(fetchRepoSummary).toHaveBeenNthCalledWith(2, "/repo/web");
    expect(screen.queryByRole("link", { name: "Details →" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("Select a repository above for details")).toHaveLength(2));
  });
});
