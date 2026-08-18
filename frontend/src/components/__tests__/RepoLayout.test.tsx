/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useOutletContext } from "react-router-dom";

vi.mock("../../api/client", () => ({
  fetchProjects: vi.fn(),
  fetchProjectsSummary: vi.fn(),
}));

import { fetchProjects, fetchProjectsSummary } from "../../api/client";
import { RepoLayout } from "../RepoLayout";
import type { RepoLayoutOutletContext } from "../RepoLayout";

beforeEach(() => {
  vi.mocked(fetchProjects).mockReset();
  vi.mocked(fetchProjectsSummary).mockReset();
  vi.mocked(fetchProjectsSummary).mockResolvedValue({ items: [] } as any);
});

function renderLayout(route = "/projects") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/projects/id/:projectId/board" element={<div>Project board</div>} />
        <Route path="/projects/id/:projectId/repos/:repoPath/*" element={<RepoLayout />} />
        <Route path="/projects/id/:projectId/*" element={<RepoLayout />} />
        <Route path="/projects/*" element={<RepoLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}

function MembershipUpdater() {
  const { onProjectUpdated } = useOutletContext<RepoLayoutOutletContext>();
  return (
    <button
      onClick={() => onProjectUpdated({
        id: "multi",
        name: "multi-project",
        repoPaths: ["/repos/keep", "/repos/new"],
        createdAt: "",
        updatedAt: "",
      })}
    >
      Apply membership
    </button>
  );
}

describe("RepoLayout project sidebar", () => {
  it("filters Projects by a partial, case-insensitive name match", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({
      items: [
        { id: "alpha", name: "alpha-project", repoPaths: ["/repos/alpha-project"] },
        { id: "beta", name: "beta-project", repoPaths: ["/repos/beta-project"] },
      ],
    } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("alpha-project")).toBeInTheDocument());
    expect(screen.getByText("beta-project")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter Projects by name"), {
      target: { value: "ALPHA" },
    });

    expect(screen.getByText("alpha-project")).toBeInTheDocument();
    expect(screen.queryByText("beta-project")).not.toBeInTheDocument();
  });

  it("shows a no-matches state when the filter matches nothing", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({
      items: [{ id: "alpha", name: "alpha-project", repoPaths: ["/repos/alpha-project"] }],
    } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("alpha-project")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Filter Projects by name"), {
      target: { value: "zzz" },
    });

    expect(screen.queryByText("alpha-project")).not.toBeInTheDocument();
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("does not render a filter box when there are no Projects", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({ items: [] } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("No Projects")).toBeInTheDocument());
    expect(screen.queryByLabelText("Filter Projects by name")).not.toBeInTheDocument();
  });

  it("does not silently select the first member repository", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({
      items: [{
        id: "multi",
        name: "multi-project",
        repoPaths: ["/repos/api", "/repos/web"],
      }],
    } as any);

    renderLayout("/projects/id/multi");

    const selector = await screen.findByLabelText("Repository");
    expect(selector).toHaveValue("");
    expect(screen.getByText("Select a member repository for Jobs, Health, Cost, and index status.")).toBeInTheDocument();
  });

  it("redirects a repository path that is not a member of the active Project", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({
      items: [{
        id: "multi",
        name: "multi-project",
        repoPaths: ["/repos/api"],
      }],
    } as any);

    renderLayout("/projects/id/multi/repos/%2Frepos%2Fother/jobs");

    expect(await screen.findByText("Project board")).toBeInTheDocument();
  });

  it("updates repository navigation from a nested membership save without reloading", async () => {
    vi.mocked(fetchProjects).mockResolvedValueOnce({
      items: [{
        id: "multi",
        name: "multi-project",
        repoPaths: ["/repos/old", "/repos/keep"],
      }],
    } as any);

    render(
      <MemoryRouter initialEntries={["/projects/id/multi/settings"]}>
        <Routes>
          <Route path="/projects" element={<RepoLayout />}>
            <Route path="id/:projectId/settings" element={<MembershipUpdater />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "old" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply membership" }));

    expect(screen.queryByRole("option", { name: "old" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "new" })).toBeInTheDocument();
  });
});
