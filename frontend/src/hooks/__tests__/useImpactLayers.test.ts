import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

vi.mock("../../api/client", () => ({ fetchImpactGraphBatch: vi.fn() }));

import { fetchImpactGraphBatch } from "../../api/client";
import { useImpactLayers } from "../useImpactLayers";
import type { DiffFileModel } from "../../api/types";

const mockFetchImpactGraphBatch = fetchImpactGraphBatch as ReturnType<typeof vi.fn>;

type ViewZoneAccessorMock = {
  removeZone: ReturnType<typeof vi.fn>;
  addZone: ReturnType<typeof vi.fn>;
  layoutZone: ReturnType<typeof vi.fn>;
};

function makeEditorRef() {
  return {
    current: {
      getModifiedEditor: () => ({
        changeViewZones: vi.fn((cb: (accessor: ViewZoneAccessorMock) => void) =>
          cb({ removeZone: vi.fn(), addZone: vi.fn().mockReturnValue("z1"), layoutZone: vi.fn() }),
        ),
        getModel: vi.fn().mockReturnValue(null),
        onMouseDown: vi.fn().mockReturnValue({ dispose: vi.fn() }),
      }),
    },
  };
}

function makeMonacoRef() {
  return {
    current: {
      editor: {
        MouseTargetType: { CONTENT_VIEW_ZONE: 8 },
      },
    },
  };
}

function makeFile(hunks?: DiffFileModel["hunks"], symbols?: DiffFileModel["symbols"]): DiffFileModel {
  return {
    path: "src/service.py",
    status: "modified",
    additions: 5,
    deletions: 2,
    hunks: hunks ?? [
      {
        oldStart: 10,
        oldLines: 5,
        newStart: 10,
        newLines: 7,
        lines: [
          { type: "context", content: "import os" },
          { type: "addition", content: "def my_function():" },
          { type: "addition", content: "    return 42" },
          { type: "context", content: "" },
        ],
      },
    ],
    symbols: symbols,
  };
}

describe("useImpactLayers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not fetch when disabled", () => {
    const file = makeFile();
    renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file,
        enabled: false,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );
    expect(mockFetchImpactGraphBatch).not.toHaveBeenCalled();
  });

  it("does not fetch when file is undefined", () => {
    renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file: undefined,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );
    expect(mockFetchImpactGraphBatch).not.toHaveBeenCalled();
  });

  it("fetches impact for detected symbols", async () => {
    mockFetchImpactGraphBatch.mockResolvedValue({
      jobId: "j",
      results: {
        my_function: {
          jobId: "j",
          target: "my_function",
          available: true,
          totalReferences: 2,
          filesAffected: 1,
          summary: "2 refs",
          references: [
            { symbol: "test_fn", file: "t.py", line: 5, tier: "verified", isTest: true, rawTier: "verified" },
            { symbol: "caller", file: "api.py", line: 20, tier: "inferred", isTest: false, rawTier: "inferred" },
          ],
        },
      },
    });

    const file = makeFile(undefined, [
      { symbol: "my_function", kind: "added", category: "breaking", lineRange: [10, 12], refCount: 2, refTiers: { verified: 1, inferred: 1 }, testFiles: [] },
    ]);
    const { result } = renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );

    await waitFor(() => {
      expect(result.current.zones).toHaveLength(1);
    });
    const zone = result.current.zones[0]!;
    expect(zone.symbolName).toBe("my_function");
    expect(zone.callers).toHaveLength(2);
    expect(zone.callers[0]!.isTest).toBe(true);
  });

  it("does not create zones when API returns unavailable", async () => {
    mockFetchImpactGraphBatch.mockResolvedValue({
      jobId: "j",
      results: {
        my_function: {
          jobId: "j",
          target: "my_function",
          available: false,
          totalReferences: 0,
          filesAffected: 0,
          summary: "",
          references: [],
        },
      },
    });

    const file = makeFile(undefined, [
      { symbol: "my_function", kind: "modified", category: "breaking", lineRange: [10, 12], refCount: 2, refTiers: { verified: 2 }, testFiles: [] },
    ]);
    const { result } = renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );

    await waitFor(() => {
      expect(mockFetchImpactGraphBatch).toHaveBeenCalled();
    });
    expect(result.current.zones).toHaveLength(0);
  });

  it("does not create zones for symbols with zero references", async () => {
    mockFetchImpactGraphBatch.mockResolvedValue({
      jobId: "j",
      results: {
        my_function: {
          jobId: "j",
          target: "my_function",
          available: true,
          totalReferences: 0,
          filesAffected: 0,
          summary: "No references",
          references: [],
        },
      },
    });

    const file = makeFile(undefined, [
      { symbol: "my_function", kind: "modified", category: "body", lineRange: [10, 12], refCount: 1, refTiers: { inferred: 1 }, testFiles: [] },
    ]);
    const { result } = renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );

    await waitFor(() => {
      expect(mockFetchImpactGraphBatch).toHaveBeenCalled();
    });
    expect(result.current.zones).toHaveLength(0);
  });

  it("handles file with no detectable symbols", () => {
    const fileNoSymbols = makeFile([
      {
        oldStart: 1,
        oldLines: 1,
        newStart: 1,
        newLines: 2,
        lines: [
          { type: "context", content: "# just a comment" },
          { type: "addition", content: "x = 42" },
        ],
      },
    ]);

    renderHook(() =>
      useImpactLayers({
        jobId: "j",
        file: fileNoSymbols,
        enabled: true,
        editorRef: makeEditorRef(),
        monacoRef: makeMonacoRef(),
        editorReady: false,
      }),
    );

    expect(mockFetchImpactGraphBatch).not.toHaveBeenCalled();
  });
});

