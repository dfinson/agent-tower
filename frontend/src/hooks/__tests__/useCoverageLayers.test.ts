import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// Mock the API client
vi.mock("../../api/client", () => ({
  fetchLineCoverage: vi.fn(),
  fetchImpactGraph: vi.fn(),
  fetchJobMotivations: vi.fn(),
}));

import { fetchLineCoverage } from "../../api/client";
import { useCoverageLayers } from "../useCoverageLayers";

const mockFetchLineCoverage = fetchLineCoverage as ReturnType<typeof vi.fn>;

function makeEditorRef(overrides: Record<string, unknown> = {}) {
  const modifiedEditor = {
    deltaDecorations: vi.fn().mockReturnValue([]),
    onMouseDown: vi.fn().mockReturnValue({ dispose: vi.fn() }),
    getDomNode: vi.fn().mockReturnValue({ getBoundingClientRect: () => ({ top: 0, left: 0 }) }),
    getScrollTop: vi.fn().mockReturnValue(0),
    getTopForLineNumber: vi.fn().mockReturnValue(50),
    ...overrides,
  };
  return {
    current: { getModifiedEditor: () => modifiedEditor },
  };
}

function makeMonacoRef() {
  return {
    current: {
      Range: class {
        constructor(
          public startLine: number,
          public startCol: number,
          public endLine: number,
          public endCol: number,
        ) {}
      },
      editor: {
        MouseTargetType: { GUTTER_GLYPH_MARGIN: 2 },
      },
    },
  };
}

describe("useCoverageLayers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not fetch when disabled", () => {
    renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: "src/foo.py",
        enabled: false,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: true,
      }),
    );
    expect(mockFetchLineCoverage).not.toHaveBeenCalled();
  });

  it("does not fetch when filePath is undefined", () => {
    renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: undefined,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: true,
      }),
    );
    expect(mockFetchLineCoverage).not.toHaveBeenCalled();
  });

  it("fetches coverage when enabled and filePath is set", async () => {
    mockFetchLineCoverage.mockResolvedValue({
      available: true,
      coveredLines: [1, 2, 3],
      uncoveredLines: [4],
      totalInstrumented: 4,
      lineRate: 0.75,
      testsByLine: { "1": [{ name: "test_a", file: "test.py", line: 10, status: "pass" }] },
    });

    const { result } = renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: "src/foo.py",
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: true,
      }),
    );

    await waitFor(() => {
      expect(mockFetchLineCoverage).toHaveBeenCalledWith("job-1", "src/foo.py");
      expect(result.current.coverage?.available).toBe(true);
    });
  });

  it("sets coverage to null when API returns unavailable", async () => {
    mockFetchLineCoverage.mockResolvedValue({ available: false });

    const { result } = renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: "src/foo.py",
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: true,
      }),
    );

    await waitFor(() => {
      expect(mockFetchLineCoverage).toHaveBeenCalled();
    });
    expect(result.current.coverage).toBeNull();
  });

  it("popover starts hidden", () => {
    const { result } = renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: undefined,
        enabled: false,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );
    expect(result.current.popover.visible).toBe(false);
  });

  it("dismissPopover hides the popover", async () => {
    mockFetchLineCoverage.mockResolvedValue({
      available: true,
      coveredLines: [1],
      uncoveredLines: [],
      totalInstrumented: 1,
      lineRate: 1.0,
      testsByLine: { "1": [{ name: "test_x", file: "t.py", line: 1, status: "pass" }] },
    });

    const { result } = renderHook(() =>
      useCoverageLayers({
        jobId: "job-1",
        filePath: "src/foo.py",
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: true,
      }),
    );

    await waitFor(() => {
      expect(result.current.coverage).not.toBeNull();
    });

    act(() => {
      result.current.dismissPopover();
    });
    expect(result.current.popover.visible).toBe(false);
  });
});
