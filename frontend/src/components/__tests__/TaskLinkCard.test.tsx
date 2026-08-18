import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { TaskLinkResponse } from "../../api/types";
import { TaskLinkCard } from "../TaskLinkCard";

function makeTaskLink(overrides: Partial<TaskLinkResponse> = {}): TaskLinkResponse {
  return {
    id: "tl-1",
    projectId: "proj-1",
    repoPath: "/repos/frontend",
    storyNodeId: "4-4-see-tasklink-cards",
    dependsOn: [],
    state: "ready",
    jobId: null,
    trackerLinkId: null,
    trackerTicketRef: null,
    promptOverride: null,
    epicId: "epic-4",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderCard(taskLink = makeTaskLink(), onStart = vi.fn()) {
  return render(
    <MemoryRouter initialEntries={["/projects/id/proj-1/board"]}>
      <Routes>
        <Route path="/projects/id/:projectId/board" element={<TaskLinkCard taskLink={taskLink} onStart={onStart} />} />
        <Route path="/jobs/:jobId" element={<div>Job detail</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TaskLinkCard", () => {
  it("shows explicit state, source, dependencies, repository, and linked Job", () => {
    renderCard(makeTaskLink({
      state: "running",
      jobId: "job-7",
      dependsOn: ["/repos/api::api-task"],
    }));

    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("Story 4-4-see-tasklink-cards")).toBeInTheDocument();
    expect(screen.getByText("api-task")).toBeInTheDocument();
    expect(screen.getByText("job-7")).toBeInTheDocument();
    expect(screen.getByText("frontend")).toBeInTheDocument();
  });

  it.each(["waiting", "ready", "running", "completed", "failed"] as const)(
    "renders the %s lifecycle state",
    (state) => {
      renderCard(makeTaskLink({ state }));
      expect(screen.getByText(state)).toBeInTheDocument();
    },
  );

  it("starts a ready root TaskLink", () => {
    const onStart = vi.fn();
    const taskLink = makeTaskLink({ state: "ready", dependsOn: [] });
    renderCard(taskLink, onStart);
    fireEvent.click(screen.getByRole("button", { name: "Start task" }));
    expect(onStart).toHaveBeenCalledWith(taskLink);
  });

  it("navigates a linked card to Job detail", () => {
    renderCard(makeTaskLink({ state: "running", jobId: "job-7" }));
    fireEvent.click(screen.getByRole("link", { name: /Task recipe/ }));
    expect(screen.getByText("Job detail")).toBeInTheDocument();
  });

  it("preserves explicit tracker-link context for tracker-backed tasks", () => {
    renderCard(makeTaskLink({
      storyNodeId: null,
      trackerTicketRef: "PAY-42",
      trackerLinkId: "tracker-link-9",
    }));
    expect(screen.getByText("Tracker PAY-42")).toBeInTheDocument();
    expect(screen.getByText("tracker-link-9")).toBeInTheDocument();
  });
});
