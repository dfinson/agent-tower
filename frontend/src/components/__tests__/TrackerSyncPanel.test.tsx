import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  createManualTaskLink: vi.fn(),
  fetchProjects: vi.fn(),
  fetchCredentials: vi.fn(),
  fetchTrackerLinks: vi.fn(),
  refreshTrackerLink: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  createManualTaskLink,
  fetchCredentials,
  fetchProjects,
  fetchTrackerLinks,
  refreshTrackerLink,
} from "../../api/client";
import { TrackerSyncPanel } from "../TrackerSyncPanel";

beforeEach(() => {
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [
      {
        id: "project-1",
        name: "Payments",
        repoPaths: ["/repos/payments"],
        createdAt: "2026-08-10T12:00:00Z",
        updatedAt: "2026-08-10T12:00:00Z",
      },
    ],
  });
  vi.mocked(fetchCredentials).mockResolvedValue({
    credentials: [
      {
        id: "credential-1",
        provider: "jira",
        label: "Acme Jira",
        baseUrl: "https://acme.atlassian.net",
        email: "dev@example.com",
        requiresEmailUpdate: false,
        createdAt: "2026-08-10T12:00:00Z",
      },
    ],
  });
  vi.mocked(fetchTrackerLinks).mockResolvedValue({
    trackerLinks: [
      {
        id: "link-1",
        projectId: "project-1",
        credentialId: "credential-1",
        externalRef: "PAY",
        createdAt: "2026-08-10T12:00:00Z",
        summary: {
          trackerLinkId: "link-1",
          tickets: [
            {
              id: "PAY-42",
              title: "Retry settlement",
              status: "In Progress",
              url: "https://acme.atlassian.net/browse/PAY-42",
            },
          ],
          lastSyncedAt: "2026-08-10T12:05:00Z",
          lastError: null,
        },
      },
    ],
  });
  vi.mocked(refreshTrackerLink).mockReset();
  vi.mocked(createManualTaskLink).mockReset();
});

describe("TrackerSyncPanel", () => {
  it("renders project, provider, link, and normalized ticket state", async () => {
    render(<TrackerSyncPanel />);

    expect(await screen.findByText("Payments")).toBeInTheDocument();
    expect(screen.getByText("Acme Jira")).toBeInTheDocument();
    expect(screen.getByText("PAY")).toBeInTheDocument();
    expect(screen.getByText("Retry settlement")).toBeInTheDocument();
    expect(screen.getByText("In Progress")).toBeInTheDocument();
  });

  it("renders never-synced and error states", async () => {
    vi.mocked(fetchTrackerLinks).mockResolvedValue({
      trackerLinks: [
        {
          id: "link-1",
          projectId: "project-1",
          credentialId: "credential-1",
          externalRef: "PAY",
          createdAt: "2026-08-10T12:00:00Z",
          summary: {
            trackerLinkId: "link-1",
            tickets: [],
            lastSyncedAt: null,
            lastError: "Tracker provider request failed",
          },
        },
      ],
    });

    render(<TrackerSyncPanel />);

    expect(await screen.findByText("Tracker provider request failed")).toBeInTheDocument();
    expect(screen.getByText("Never synced")).toBeInTheDocument();
  });

  it("manually refreshes one link and renders the returned state", async () => {
    vi.mocked(refreshTrackerLink).mockResolvedValue({
      trackerLinkId: "link-1",
      tickets: [
        {
          id: "PAY-43",
          title: "New ticket",
          status: "Ready",
          url: null,
        },
      ],
      lastSyncedAt: "2026-08-10T12:10:00Z",
      lastError: null,
    });

    render(<TrackerSyncPanel />);
    const refreshButton = await screen.findByRole("button", { name: "Refresh PAY" });
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(refreshTrackerLink).toHaveBeenCalledWith("project-1", "link-1");
    });
    expect(await screen.findByText("New ticket")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("shows an empty state when no Projects have tracker links", async () => {
    vi.mocked(fetchTrackerLinks).mockResolvedValue({ trackerLinks: [] });

    render(<TrackerSyncPanel />);

    expect(await screen.findByText("No tracker links attached yet.")).toBeInTheDocument();
  });

  it("assigns a synced ticket with its explicit TrackerLink", async () => {
    vi.mocked(createManualTaskLink).mockResolvedValue({ id: "task-1" } as never);
    render(<TrackerSyncPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Assign task for PAY-42" }));
    const createButton = screen.getByRole("button", { name: "Create TaskLink" });
    expect(createButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Task repository"), {
      target: { value: "/repos/payments" },
    });
    fireEvent.change(screen.getByLabelText("Task prompt"), {
      target: { value: "Implement payment retry" },
    });
    fireEvent.click(createButton);

    await waitFor(() => {
      expect(createManualTaskLink).toHaveBeenCalledWith("project-1", {
        repoPath: "/repos/payments",
        trackerLinkId: "link-1",
        trackerTicketRef: "PAY-42",
        promptOverride: "Implement payment retry",
        outputRoutes: [],
      });
    });
  });

  it("persists the explicit tracker-write output route when selected", async () => {
    vi.mocked(createManualTaskLink).mockResolvedValue({ id: "task-1" } as never);
    render(<TrackerSyncPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Assign task for PAY-42" }));
    fireEvent.change(screen.getByLabelText("Task repository"), {
      target: { value: "/repos/payments" },
    });
    fireEvent.change(screen.getByLabelText("Task prompt"), {
      target: { value: "Implement payment retry" },
    });
    fireEvent.click(screen.getByRole("checkbox", {
      name: /approved tracker comment/i,
    }));
    fireEvent.click(screen.getByRole("button", { name: "Create TaskLink" }));

    await waitFor(() => {
      expect(createManualTaskLink).toHaveBeenCalledWith(
        "project-1",
        expect.objectContaining({ outputRoutes: ["tracker_write"] }),
      );
    });
  });
});
