import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { TaskLinkResponse } from "../../api/types";
import { TaskLinkCard } from "../TaskLinkCard";

function makeTaskLink(overrides: Partial<TaskLinkResponse> = {}): TaskLinkResponse {
  return {
    id: "tl-1",
    projectId: "proj-1",
    repoPath: "/repos/frontend",
    storyNodeId: "4-4-see-tasklink-cards",
    dependsOn: [],
    jobId: null,
    trackerTicketRef: null,
    promptOverride: null,
    epicId: "epic-4",
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("TaskLinkCard", () => {
  it("renders the story node id and repo name", () => {
    render(<TaskLinkCard taskLink={makeTaskLink()} satisfied />);
    expect(screen.getByText("4-4-see-tasklink-cards")).toBeInTheDocument();
    expect(screen.getByText("frontend")).toBeInTheDocument();
    expect(screen.getByText("chained")).toBeInTheDocument();
  });

  it("falls back to the tracker ticket ref when there is no story node id", () => {
    render(
      <TaskLinkCard
        taskLink={makeTaskLink({ storyNodeId: null, trackerTicketRef: "JIRA-123" })}
        satisfied
      />,
    );
    expect(screen.getByText("JIRA-123")).toBeInTheDocument();
  });

  it("renders a satisfied badge and normal styling when dependencies are satisfied", () => {
    render(<TaskLinkCard taskLink={makeTaskLink()} satisfied />);
    expect(screen.getByText("deps satisfied")).toBeInTheDocument();
    expect(screen.getByLabelText(/dependencies satisfied/)).not.toHaveClass("opacity-60");
  });

  it("renders a greyed-out waiting badge naming the blocking dependency when unsatisfied", () => {
    render(
      <TaskLinkCard
        taskLink={makeTaskLink({ dependsOn: ["/repos/frontend::add-sca"] })}
        satisfied={false}
        blockingLabel="add-sca"
      />,
    );
    expect(screen.getByText("waiting on add-sca")).toBeInTheDocument();
    expect(screen.getByLabelText(/waiting on dependencies/)).toHaveClass("opacity-60");
  });

  it("renders a generic waiting badge when no blocking label is provided", () => {
    render(
      <TaskLinkCard
        taskLink={makeTaskLink({ dependsOn: ["/repos/frontend::add-sca"] })}
        satisfied={false}
        blockingLabel={null}
      />,
    );
    expect(screen.getByText("waiting")).toBeInTheDocument();
  });
});
