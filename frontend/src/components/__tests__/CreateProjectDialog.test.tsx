/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  createProject: vi.fn(),
  registerRepo: vi.fn(),
  createRepo: vi.fn(),
  unregisterRepo: vi.fn(),
  browseDirectories: vi.fn(),
}));

import { createProject, registerRepo, createRepo, browseDirectories, unregisterRepo } from "../../api/client";
import { CreateProjectDialog } from "../CreateProjectDialog";

beforeEach(() => {
  vi.mocked(createProject).mockReset();
  vi.mocked(registerRepo).mockReset();
  vi.mocked(createRepo).mockReset();
  vi.mocked(unregisterRepo).mockReset();
  vi.mocked(unregisterRepo).mockResolvedValue(undefined);
  vi.mocked(browseDirectories).mockReset();
  vi.mocked(browseDirectories).mockResolvedValue({
    current: "/home/user",
    parent: "/home",
    items: [
      { name: "repo-a", path: "/home/user/repo-a", isGitRepo: true },
      { name: "not-a-repo", path: "/home/user/not-a-repo", isGitRepo: false },
    ],
  });
});

describe("CreateProjectDialog", () => {
  it("blocks creation with an error when no name is entered", async () => {
    const onCreated = vi.fn();
    render(<CreateProjectDialog open onClose={() => {}} onCreated={onCreated} />);

    await waitFor(() => expect(screen.getByText("repo-a")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    expect(await screen.findByText("Project name is required.")).toBeInTheDocument();
    expect(createProject).not.toHaveBeenCalled();
  });

  it("blocks creation with an error when no member repository is added", async () => {
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "My Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    expect(
      await screen.findByText("Add at least one member repository before creating the Project."),
    ).toBeInTheDocument();
    expect(createProject).not.toHaveBeenCalled();
  });

  it("creates a project from a browsed repo and calls onCreated", async () => {
    vi.mocked(createProject).mockResolvedValueOnce({
      id: "proj-1",
      name: "My Project",
      repoPaths: ["/home/user/repo-a"],
    } as any);
    const onCreated = vi.fn();
    render(<CreateProjectDialog open onClose={() => {}} onCreated={onCreated} />);

    await waitFor(() => expect(screen.getByText("repo-a")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "My Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() =>
      expect(createProject).toHaveBeenCalledWith({
        name: "My Project",
        repoPaths: ["/home/user/repo-a"],
      }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it("registers a repo via clone/register mode and adds it to the member list", async () => {
    vi.mocked(registerRepo).mockResolvedValueOnce({
      path: "/home/user/cloned-repo",
      source: "https://example.com/repo.git",
      cloned: true,
      registered: true,
    });
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Clone / register" }));
    fireEvent.change(screen.getByPlaceholderText("Local path or git clone URL"), {
      target: { value: "https://example.com/repo.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register repository" }));

    await waitFor(() => expect(registerRepo).toHaveBeenCalledWith("https://example.com/repo.git", undefined));
    expect(await screen.findByText("/home/user/cloned-repo")).toBeInTheDocument();
  });

  it("creates a repo via init mode and adds it to the member list", async () => {
    vi.mocked(createRepo).mockResolvedValueOnce({ path: "/home/user/new-repo", name: "new-repo" });
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Init new" }));
    fireEvent.change(screen.getByPlaceholderText("/absolute/path/to/new-repo"), {
      target: { value: "/home/user/new-repo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create repository" }));

    await waitFor(() => expect(createRepo).toHaveBeenCalledWith("/home/user/new-repo", undefined));
    expect(await screen.findByText("/home/user/new-repo")).toBeInTheDocument();
  });

  it("surfaces an error and does not call onCreated when project creation fails", async () => {
    vi.mocked(createProject).mockRejectedValueOnce(new Error("boom"));
    const onCreated = vi.fn();
    render(<CreateProjectDialog open onClose={() => {}} onCreated={onCreated} />);

    await waitFor(() => expect(screen.getByText("repo-a")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "My Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    expect(await screen.findByText(/boom/)).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("surfaces repository validation failures without persisting a Project", async () => {
    vi.mocked(createProject).mockRejectedValueOnce(
      new Error("Repository '/home/user/repo-a' does not exist or is not a valid Git repository."),
    );
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    await screen.findByText("repo-a");
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.change(screen.getByLabelText("Project name"), {
      target: { value: "My Project" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    expect(await screen.findByText(/not a valid Git repository/)).toBeInTheDocument();
    expect(screen.getByText("/home/user/repo-a")).toBeInTheDocument();
  });

  it("rolls back staged registration when creation fails and reports retained files", async () => {
    vi.mocked(registerRepo).mockResolvedValueOnce({
      path: "/home/user/cloned-repo",
      source: "https://example.com/repo.git",
      cloned: true,
      registered: true,
    });

    vi.mocked(createProject).mockRejectedValueOnce(new Error("Project save failed"));
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Clone / register" }));
    fireEvent.change(screen.getByPlaceholderText("Local path or git clone URL"), {
      target: { value: "https://example.com/repo.git" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register repository" }));
    await screen.findByText("/home/user/cloned-repo");
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "My Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => expect(unregisterRepo).toHaveBeenCalledWith("/home/user/cloned-repo"));
    expect(
      await screen.findByText(/Repository files and any completed index remain at: \/home\/user\/cloned-repo/),
    ).toBeInTheDocument();
  });

  it("does not compensate a pre-existing registration when project creation fails", async () => {
    vi.mocked(registerRepo).mockResolvedValueOnce({
      path: "/home/user/existing-repo",
      source: "/home/user/existing-repo",
      cloned: false,
      registered: false,
    });
    vi.mocked(createProject).mockRejectedValueOnce(new Error("Project save failed"));
    render(<CreateProjectDialog open onClose={() => {}} onCreated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Clone / register" }));
    fireEvent.change(screen.getByPlaceholderText("Local path or git clone URL"), {
      target: { value: "/home/user/existing-repo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register repository" }));
    await screen.findByText("/home/user/existing-repo");
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "My Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    expect(await screen.findByText(/Project save failed/)).toBeInTheDocument();
    expect(unregisterRepo).not.toHaveBeenCalled();
  });
});
