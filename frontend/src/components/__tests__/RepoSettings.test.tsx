import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api/client", () => ({
  request: vi.fn().mockResolvedValue({}),
  fetchProject: vi.fn(),
  fetchRepoDetail: vi.fn(),
  fetchCredentials: vi.fn(),
  fetchTrackerLinks: vi.fn(),
  createTrackerLink: vi.fn(),
  updateProject: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  createTrackerLink,
  fetchCredentials,
  fetchProject,
  fetchRepoDetail,
  fetchTrackerLinks,
  updateProject,
} from "../../api/client";
import { RepoSettings } from "../RepoSettings";

describe("RepoSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("allows editing the owning project membership and saves it", async () => {
    vi.mocked(fetchProject).mockResolvedValue({
      id: "project-1",
      name: "Alpha project",
      repoPaths: ["/repo/app", "/repo/shared"],
      createdAt: "2024-01-01T00:00:00Z",
      updatedAt: "2024-01-02T00:00:00Z",
    } as any);

    vi.mocked(fetchRepoDetail).mockResolvedValue({
      path: "/repo/app",
      originUrl: "https://github.com/example/app",
      baseBranch: "main",
      currentBranch: "feature/test",
      platform: "github",
      activeJobCount: 2,
      recentJobs: [],
    } as any);

    vi.mocked(fetchCredentials).mockResolvedValue({
      credentials: [{
        id: "cred-1",
        provider: "github",
        label: "Alpha GitHub",
        baseUrl: "https://api.github.com",
        createdAt: "2024-01-01T00:00:00Z",
      }],
    } as any);

    vi.mocked(fetchTrackerLinks).mockResolvedValue({
      trackerLinks: [{
        id: "link-1",
        projectId: "project-1",
        credentialId: "cred-1",
        externalRef: "Alpha board",
        createdAt: "2024-01-01T00:00:00Z",
        summary: null,
      }],
    } as any);

    vi.mocked(createTrackerLink).mockResolvedValue({
      id: "link-2",
      projectId: "project-1",
      credentialId: "cred-1",
      externalRef: "Alpha board",
      createdAt: "2024-01-01T00:00:00Z",
      summary: null,
    } as any);

    vi.mocked(updateProject).mockResolvedValue({
      id: "project-1",
      name: "Alpha project v2",
      repoPaths: ["/repo/app", "/repo/shared", "/repo/new-tool"],
      createdAt: "2024-01-01T00:00:00Z",
      updatedAt: "2024-01-03T00:00:00Z",
    } as any);

    render(
      <MemoryRouter initialEntries={["/projects/id/project-1"]}>
        <Routes>
          <Route path="/projects/id/:projectId" element={<RepoSettings />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Project Settings")).toBeInTheDocument();
    });

    expect(screen.getByText("Integrations & board sync")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /manage integrations/i })).toHaveAttribute("href", "/settings");
    expect(screen.getByLabelText(/select tracker credential/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/board or org ref/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/board or org ref/i), { target: { value: "Alpha board v2" } });
    fireEvent.click(screen.getByRole("button", { name: /attach/i }));

    await waitFor(() => {
      expect(createTrackerLink).toHaveBeenCalledWith("project-1", {
        credentialId: "cred-1",
        externalRef: "Alpha board v2",
      });
    });

    const nameInput = screen.getByDisplayValue("Alpha project");
    fireEvent.change(nameInput, { target: { value: "Alpha project v2" } });

    const addInput = screen.getByPlaceholderText("/absolute/path/to/repo");
    fireEvent.change(addInput, { target: { value: "/repo/new-tool" } });
    fireEvent.click(screen.getByRole("button", { name: /add/i }));

    fireEvent.click(screen.getByRole("button", { name: /save project/i }));

    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith("project-1", {
        name: "Alpha project v2",
        repoPaths: ["/repo/app", "/repo/shared", "/repo/new-tool"],
      });
    });
  });
});
