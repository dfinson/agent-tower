import { describe, it, expect, beforeEach } from "vitest";
import { useStore } from "../index";
import { normalizeTFEvent } from "../sseNormalize";

/**
 * Regression coverage for the activity-timeline group heading.
 *
 * The backend emits `turn.summary` from TraceForge's native `TitleUpdate`.
 * Activity-kind updates carry `activity_label` (TF's own title); step-kind
 * updates carry none. If the label is dropped anywhere along that path the
 * timeline renders a blank activity heading.
 */

/** Feed a raw TF wire frame through the same adapter `useSSE` uses. */
function dispatchTF(payload: Record<string, unknown>) {
  const normalized = normalizeTFEvent({
    kind: "turn.summary",
    session_id: "job-1",
    timestamp: "2025-01-01T00:00:00Z",
    payload,
  });
  useStore.getState().dispatchSSEEvent("turn.summary", normalized);
}

beforeEach(() => {
  useStore.setState({ activityTimelines: {} });
});

describe("turn.summary → activity timeline", () => {
  it("gives the activity group a nonblank label from a native activity update", () => {
    dispatchTF({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      activity_label: "Setting up environment",
      is_new_activity: true,
    });

    const timeline = useStore.getState().activityTimelines["job-1"]!;
    expect(timeline.activities).toHaveLength(1);
    expect(timeline.activities[0]!.label).toBe("Setting up environment");
    expect(timeline.activities[0]!.label).not.toBe("");
  });

  it("keeps the activity label when a labelless step update follows", () => {
    dispatchTF({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      activity_label: "Setting up environment",
      is_new_activity: true,
    });
    // Step-kind updates carry no activity_label — they must not erase it.
    dispatchTF({
      turn_id: "step-1",
      title: "Reading config file",
      activity_id: "act-1",
      is_new_activity: false,
    });

    const timeline = useStore.getState().activityTimelines["job-1"]!;
    expect(timeline.activities).toHaveLength(1);
    expect(timeline.activities[0]!.label).toBe("Setting up environment");
    expect(timeline.activities[0]!.steps.map((s) => s.title)).toEqual([
      "Setting up environment",
      "Reading config file",
    ]);
  });
});
