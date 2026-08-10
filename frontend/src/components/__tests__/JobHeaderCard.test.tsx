import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { JobSummary } from "../../store";
import { JobHeaderCard } from "../JobHeaderCard";

function makeJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    id: "job-1",
    title: "Test Job",
    prompt: "Fix the bug",
    state: "running",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    completedAt: null,
    repo: "/tmp/test-repo",
    branch: "cpl/job-1",
    baseRef: "main",
    worktreePath: null,
    prUrl: null,
    resolution: null,
    archivedAt: null,
    failureReason: null,
    progressHeadline: null,
    model: "claude-sonnet-4-5-20250514",
    sdk: "copilot",
    ...overrides,
  };
}

const actionProps = {
  canCancel: false,
  canResume: false,
  needsResolution: false,
  hasChanges: false,
  hasMergeConflict: false,
  isResolved: false,
  canArchive: false,
  jobState: "running",
  archivedAt: null,
  actionLoading: false,
  resolveLoading: null,
  onCancelOpen: vi.fn(),
  onResume: vi.fn(),
  onResolve: vi.fn(),
  onDiscardOpen: vi.fn(),
  onMarkDoneOpen: vi.fn(),
  onCompleteOpen: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("JobHeaderCard", () => {
  it("shows failure details", () => {
    render(
      <MemoryRouter>
        <JobHeaderCard
          job={makeJob({ state: "failed", failureReason: "Agent process exited with code 1: Out of memory" })}
          isPreparing={false}
          hasMergeConflict={false}
          onNavigateHome={vi.fn()}
          onCostClick={vi.fn()}
          actionProps={actionProps}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Job failed")).toBeInTheDocument();
    expect(screen.getByText("Agent process exited with code 1: Out of memory")).toBeInTheDocument();
  });

  it("shows fallback failure details when none are available", () => {
    render(
      <MemoryRouter>
        <JobHeaderCard
          job={makeJob({ state: "failed", failureReason: null })}
          isPreparing={false}
          hasMergeConflict={false}
          onNavigateHome={vi.fn()}
          onCostClick={vi.fn()}
          actionProps={actionProps}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Job failed")).toBeInTheDocument();
    expect(screen.getByText("No additional details available")).toBeInTheDocument();
  });

  it("shows canceled, completed, and model downgrade banners", () => {
    const { rerender } = render(
      <MemoryRouter>
        <JobHeaderCard
          job={makeJob({ state: "canceled" })}
          isPreparing={false}
          hasMergeConflict={false}
          onNavigateHome={vi.fn()}
          onCostClick={vi.fn()}
          actionProps={actionProps}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Job canceled")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <JobHeaderCard
          job={makeJob({ state: "completed", resolution: "merged", completedAt: new Date().toISOString() })}
          isPreparing={false}
          hasMergeConflict={false}
          onNavigateHome={vi.fn()}
          onCostClick={vi.fn()}
          actionProps={actionProps}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Job completed")).toBeInTheDocument();
    expect(screen.getByText("Changes merged into base branch")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <JobHeaderCard
          job={makeJob({
            state: "failed",
            failureReason: "Model downgraded: requested claude-opus-4-20250514 but received claude-sonnet-4-5-20250514",
            modelDowngraded: true,
            requestedModel: "claude-opus-4-20250514",
            actualModel: "claude-sonnet-4-5-20250514",
          })}
          isPreparing={false}
          hasMergeConflict={false}
          onNavigateHome={vi.fn()}
          onCostClick={vi.fn()}
          actionProps={actionProps}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Model downgraded")).toBeInTheDocument();
    expect(screen.getByText("claude-opus-4-20250514 → claude-sonnet-4-5-20250514")).toBeInTheDocument();
  });
});
