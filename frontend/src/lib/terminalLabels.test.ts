import { describe, expect, it } from "vitest";

import { formatJobTerminalLabel } from "./terminalLabels";

describe("formatJobTerminalLabel", () => {
  it("prefers repo and worktree name", () => {
    expect(
      formatJobTerminalLabel(
        {
          repo: "/repos/codeplane",
          worktreeName: "fix-mobile-terminal",
          worktreePath: "/repos/codeplane/.codeplane-worktrees/fix-mobile-terminal",
          branch: "feat/mobile-terminal",
        },
        "job-1",
      ),
    ).toBe("codeplane:fix-mobile-terminal");
  });

  it("falls back to worktree path leaf and job id", () => {
    expect(
      formatJobTerminalLabel(
        {
          repo: "/repos/codeplane",
          worktreeName: null,
          worktreePath: "/repos/codeplane/.codeplane-worktrees/job-1",
          branch: null,
        },
        "job-1",
      ),
    ).toBe("codeplane:job-1");
  });
});