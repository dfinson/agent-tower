import { describe, expect, it } from "vitest";
import type { TranscriptEntry } from "../store";
import {
  mergeTranscriptEntries,
  sameTranscriptEntry,
  transcriptReactKey,
} from "./transcriptIdentity";

function entry(overrides: Partial<TranscriptEntry> = {}): TranscriptEntry {
  return {
    jobId: "job-1",
    timestamp: "2026-01-01T00:00:00Z",
    kind: "message.assistant",
    content: "done",
    ...overrides,
  };
}

describe("transcript identity", () => {
  it("deduplicates by TraceForge event id before canonical sequence", () => {
    expect(sameTranscriptEntry(
      entry({ eventId: "evt-1", sequence: 10 }),
      entry({ eventId: "evt-1", sequence: 11 }),
    )).toBe(true);
  });

  it("does not collapse distinct events that share an invalid legacy sequence", () => {
    const merged = mergeTranscriptEntries(
      [entry({ eventId: "evt-1", sequence: 0, content: "first" })],
      [entry({ eventId: "evt-2", sequence: 0, content: "second" })],
    );
    expect(merged.map((item) => item.eventId)).toEqual(["evt-1", "evt-2"]);
  });

  it("does not use zero as identity when canonical event ids are missing", () => {
    const merged = mergeTranscriptEntries(
      [entry({ sequence: 0, timestamp: "2026-01-01T00:00:00Z", content: "first" })],
      [entry({ sequence: 0, timestamp: "2026-01-01T00:00:01Z", content: "second" })],
    );
    expect(merged).toHaveLength(2);
  });

  it("orders only when every event has a canonical sequence", () => {
    expect(mergeTranscriptEntries(
      [entry({ eventId: "evt-2", sequence: 2 })],
      [entry({ eventId: "evt-1", sequence: 1 })],
    ).map((item) => item.eventId)).toEqual(["evt-1", "evt-2"]);

    expect(mergeTranscriptEntries(
      [entry({ eventId: "evt-2" })],
      [entry({ eventId: "evt-1", sequence: 1 })],
    ).map((item) => item.eventId)).toEqual(["evt-2", "evt-1"]);
  });

  it("produces unique React keys for entries without canonical identity", () => {
    const item = entry({ eventId: undefined, sequence: undefined });
    expect(transcriptReactKey(item, 0)).not.toBe(transcriptReactKey(item, 1));
  });
});
