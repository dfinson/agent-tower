/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../api/client", () => ({
  fetchProjectsSummary: vi.fn(),
  createProject: vi.fn(),
  registerRepo: vi.fn(),
  createRepo: vi.fn(),
  browseDirectories: vi.fn(),
}));

import { fetchProjectsSummary, createProject, browseDirectories } from "../../api/client";
import { ProjectsOverview } from "../ProjectsOverview";

function makeSummary(overrides: Partial<any> = {}) {
  return {
    id: "proj-1",
    name: "My Project",
    repoPaths: ["/repos/my-project"],
    activeJobCount: 0,
    awaitingInputCount: 0,
    failedCount: 0,
    lastActivityAt: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchProjectsSummary).mockReset();
  vi.mocked(createProject).mockReset();
  vi.mocked(browseDirectories).mockReset();
  vi.mocked(browseDirectories).mockResolvedValue({
    current: "/home/user",
    parent: null,
    items: [{ name: "new-repo", path: "/home/user/new-repo", isGitRepo: true }],
  });
});

describe("ProjectsOverview", () => {
  it("renders a card for a zero-job project with a 'No jobs yet' affordance", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [makeSummary()],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("My Project")).toBeInTheDocument());
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
  });

  it("renders a card per project with bucketed counts", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [
        makeSummary({ id: "proj-1", name: "Alpha", activeJobCount: 2, awaitingInputCount: 1, failedCount: 3 }),
        makeSummary({ id: "proj-2", name: "Beta" }),
      ],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("2 active")).toBeInTheDocument();
    expect(screen.getByText("1 awaiting")).toBeInTheDocument();
    expect(screen.getByText("3 failed")).toBeInTheDocument();
  });

  it("fetches the summary exactly once on mount, not per project (batch call)", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [makeSummary({ id: "proj-1" }), makeSummary({ id: "proj-2" }), makeSummary({ id: "proj-3" })],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(fetchProjectsSummary).toHaveBeenCalledTimes(1));
  });

  it("shows an empty state when there are no projects", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({ items: [] } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("No Projects registered")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /New Project/i })).toBeInTheDocument();
  });

  it("opens the Create Project dialog and creates a project from the empty-state CTA", async () => {
    vi.mocked(fetchProjectsSummary)
      .mockResolvedValueOnce({ items: [] } as any)
      .mockResolvedValueOnce({ items: [makeSummary({ id: "proj-1", name: "New Project" })] } as any);
    vi.mocked(createProject).mockResolvedValueOnce({
      id: "proj-1",
      name: "New Project",
      repoPaths: ["/home/user/new-repo"],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("No Projects registered")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /New Project/i }));

    await waitFor(() => expect(screen.getByText("new-repo")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "New Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() =>
      expect(createProject).toHaveBeenCalledWith({
        name: "New Project",
        repoPaths: ["/home/user/new-repo"],
      }),
    );
  });

  it("shows a persistent New Project action in the header when projects already exist", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [makeSummary({ id: "proj-1", name: "Alpha" })],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /New Project/i })).toBeInTheDocument();
  });

  it("filters cards by a partial, case-insensitive name match", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [
        makeSummary({ id: "proj-1", name: "Alpha" }),
        makeSummary({ id: "proj-2", name: "Beta" }),
      ],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter Projects by name"), { target: { value: "alp" } });

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Beta")).not.toBeInTheDocument();
  });

  it("shows a no-matches empty state when the filter matches nothing", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [makeSummary({ id: "proj-1", name: "Alpha" })],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Filter Projects by name"), { target: { value: "zzz" } });

    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.getByText('No Projects match "zzz"')).toBeInTheDocument();
  });

  it("shows a combined attention count summed across all projects' awaiting+failed", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [
        makeSummary({ id: "proj-1", name: "Alpha", awaitingInputCount: 2, failedCount: 1 }),
        makeSummary({ id: "proj-2", name: "Beta", awaitingInputCount: 0, failedCount: 3 }),
      ],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    // 2 + 1 + 0 + 3 = 6
    const badge = await screen.findByTestId("attention-badge");
    expect(badge).toHaveTextContent("6");
    expect(badge.className).toMatch(/alarming/);
  });

  it("renders the attention badge non-alarmingly when no project needs attention", async () => {
    vi.mocked(fetchProjectsSummary).mockResolvedValueOnce({
      items: [
        makeSummary({ id: "proj-1", name: "Alpha" }),
        makeSummary({ id: "proj-2", name: "Beta" }),
      ],
    } as any);

    render(
      <MemoryRouter>
        <ProjectsOverview />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const badge = await screen.findByTestId("attention-badge");
    expect(badge).toHaveTextContent("0");
    expect(badge.className).toMatch(/neutral/);
    expect(badge.className).not.toMatch(/alarming/);
  });
});
