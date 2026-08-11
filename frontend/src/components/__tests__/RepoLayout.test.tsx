/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("../../api/client", () => ({
  fetchRepos: vi.fn(),
  fetchProjectsSummary: vi.fn(),
}));

import { fetchRepos, fetchProjectsSummary } from "../../api/client";
import { RepoLayout } from "../RepoLayout";

beforeEach(() => {
  vi.mocked(fetchRepos).mockReset();
  vi.mocked(fetchProjectsSummary).mockReset();
  vi.mocked(fetchProjectsSummary).mockResolvedValue({ items: [] } as any);
});

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/repos"]}>
      <Routes>
        <Route path="/repos/*" element={<RepoLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RepoLayout sidebar filter", () => {
  it("filters the repo list by a partial, case-insensitive name match", async () => {
    vi.mocked(fetchRepos).mockResolvedValueOnce({
      items: ["/repos/alpha-project", "/repos/beta-project"],
    } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("alpha-project")).toBeInTheDocument());
    expect(screen.getByText("beta-project")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter repositories by name"), {
      target: { value: "ALPHA" },
    });

    expect(screen.getByText("alpha-project")).toBeInTheDocument();
    expect(screen.queryByText("beta-project")).not.toBeInTheDocument();
  });

  it("shows a no-matches state when the filter matches nothing", async () => {
    vi.mocked(fetchRepos).mockResolvedValueOnce({
      items: ["/repos/alpha-project"],
    } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("alpha-project")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Filter repositories by name"), {
      target: { value: "zzz" },
    });

    expect(screen.queryByText("alpha-project")).not.toBeInTheDocument();
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("does not render a filter box when there are no repositories", async () => {
    vi.mocked(fetchRepos).mockResolvedValueOnce({ items: [] } as any);

    renderLayout();

    await waitFor(() => expect(screen.getByText("No repositories")).toBeInTheDocument());
    expect(screen.queryByLabelText("Filter repositories by name")).not.toBeInTheDocument();
  });
});
