/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the API client
vi.mock("../../api/client", () => ({
  fetchSettings: vi.fn(),
  updateSettings: vi.fn(),
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

import { fetchSettings, updateSettings } from "../../api/client";
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
};

beforeEach(() => {
  vi.mocked(fetchSettings).mockResolvedValue(defaultSettings as any);
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

  it("displays Runtime section", async () => {
    render(
      <MemoryRouter>
        <SettingsScreen />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Runtime")).toBeInTheDocument();
    });
    expect(
      screen.queryByText("Tracker poll interval (seconds)"),
    ).not.toBeInTheDocument();
  });

  it("shows error toast when settings fail to load", async () => {
    const { toast } = await import("sonner");
    vi.mocked(fetchSettings).mockRejectedValueOnce(new Error("fail"));
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
