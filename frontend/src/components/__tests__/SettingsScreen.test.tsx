/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the API client
vi.mock("../../api/client", () => ({
  fetchSettings: vi.fn(),
  updateSettings: vi.fn(),
  fetchRepos: vi.fn(),
  unregisterRepo: vi.fn(),
  fetchSidecarTemplates: vi.fn().mockResolvedValue({ items: [] }),
  request: vi.fn().mockResolvedValue(null),
  fetchProjects: vi.fn().mockResolvedValue({ items: [] }),
  fetchCredentials: vi.fn().mockResolvedValue({ credentials: [] }),
  fetchTrackerLinks: vi.fn().mockResolvedValue({ trackerLinks: [] }),
  refreshTrackerLink: vi.fn(),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Mock AddRepoModal
vi.mock("../AddRepoModal", () => ({
  AddRepoModal: () => null,
}));

import { fetchSettings, fetchRepos, updateSettings } from "../../api/client";
import { SettingsScreen } from "../SettingsScreen";

const defaultSettings = {
  maxConcurrentJobs: 2,
  autoPush: true,
  cleanupWorktree: true,
  deleteBranchAfterMerge: true,
  artifactRetentionDays: 30,
  maxArtifactSizeMb: 100,
  autoArchiveDays: 90,
  maxTurns: 3,
  trackerPollIntervalSeconds: 300,
};

beforeEach(() => {
  vi.mocked(fetchSettings).mockResolvedValue(defaultSettings as any);
  vi.mocked(fetchRepos).mockResolvedValue({ items: ["/repos/my-app"] } as any);
  vi.mocked(updateSettings).mockReset();
});

describe("SettingsScreen", () => {
  it("renders Settings heading after loading", async () => {
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Settings")).toBeInTheDocument();
    });
  });

  it("loads and displays repos", async () => {
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("/repos/my-app")).toBeInTheDocument();
    });
  });

  it("displays Repositories section with count", async () => {
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Repositories (1)")).toBeInTheDocument();
    });
  });

  it("displays Runtime section", async () => {
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Runtime")).toBeInTheDocument();
    });
  });

  it("edits and saves the tracker polling interval", async () => {
    vi.mocked(updateSettings).mockImplementation(async (settings) => settings as any);
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );

    const field = await screen.findByLabelText("Tracker poll interval (seconds)");
    fireEvent.change(field, { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ trackerPollIntervalSeconds: 45 }),
      );
    });
  });

  it("shows error toast when settings fail to load", async () => {
    const { toast } = await import("sonner");
    vi.mocked(fetchSettings).mockRejectedValueOnce(new Error("fail"));
    vi.mocked(fetchRepos).mockRejectedValueOnce(new Error("fail"));
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to load settings");
    });
  });
});
