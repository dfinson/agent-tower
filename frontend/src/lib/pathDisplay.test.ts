import { describe, expect, it } from "vitest";
import { repositoryRelativePath, trimWorktreeRoot } from "./pathDisplay";

describe("repositoryRelativePath", () => {
  it("returns Windows repository-relative paths without a leading slash", () => {
    expect(repositoryRelativePath(
      String.raw`C:\Users\david\.codeplane-worktrees\codeplane\audit\backend\api\jobs.py`,
      String.raw`C:\Users\david\.codeplane-worktrees\codeplane\audit`,
    )).toBe("backend/api/jobs.py");
  });

  it("compares Windows roots case-insensitively and enforces a path boundary", () => {
    expect(repositoryRelativePath(
      String.raw`c:\REPO\src\main.ts`,
      String.raw`C:\repo`,
    )).toBe("src/main.ts");
    expect(repositoryRelativePath(
      String.raw`C:\repository\src\main.ts`,
      String.raw`C:\repo`,
    )).toBeNull();
  });

  it("handles POSIX paths and rejects paths outside the worktree", () => {
    expect(repositoryRelativePath("/work/job/src/main.py", "/work/job")).toBe("src/main.py");
    expect(repositoryRelativePath("/work/other/main.py", "/work/job")).toBeNull();
  });

  it("handles UNC paths case-insensitively without losing their boundary", () => {
    expect(repositoryRelativePath(
      String.raw`\\SERVER\Share\repo\src\main.ts`,
      String.raw`\\server\share\repo`,
    )).toBe("src/main.ts");
    expect(repositoryRelativePath(
      String.raw`\\server\share\repository\src\main.ts`,
      String.raw`\\server\share\repo`,
    )).toBeNull();
  });

  it("rejects traversal and absolute paths when no worktree root is known", () => {
    expect(repositoryRelativePath("../secret.txt", "/work/job")).toBeNull();
    expect(repositoryRelativePath("/work/job/src/main.py")).toBeNull();
  });

  it("keeps already-relative repository paths intact", () => {
    expect(repositoryRelativePath("src/components/App.tsx", "/work/job")).toBe("src/components/App.tsx");
  });
});

describe("trimWorktreeRoot", () => {
  it("only replaces the exact Windows worktree root", () => {
    expect(trimWorktreeRoot(
      String.raw`Get-Content C:\repo\src\main.ts`,
      String.raw`C:\repo`,
    )).toBe(String.raw`Get-Content .\src\main.ts`);
    expect(trimWorktreeRoot(
      String.raw`Get-Content C:\repository\src\main.ts`,
      String.raw`C:\repo`,
    )).toBe(String.raw`Get-Content C:\repository\src\main.ts`);
  });
});
