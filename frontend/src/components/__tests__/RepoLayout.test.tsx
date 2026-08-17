/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../../api/client", () => ({
  fetchProjects: vi.fn(),
  fetchProjectsSummary: vi.fn(),
}));

import { fetchProjects, fetchProjectsSummary } from "../../api/client";
import { RepoLayout } from "../RepoLayout";

beforeEach(() => {
  vi.mocked(fetchProjects).mockReset();
  vi.mocked(fetchProjectsSummary).mockReset();
  vi.mocked(fetchProjectsSummary).mockResolvedValue({ items: [] } as any);
});

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/projects"]}>
      <Routes>
        <Route path="/projects/*" element={<RepoLayout />} />
      </Routes>
    </MemoryRouter>,
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
});
