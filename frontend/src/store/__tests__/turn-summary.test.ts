import { describe, it, expect, beforeEach } from "vitest";
import { useStore } from "../index";
import { normalizeTFEvent, type TFSessionEvent } from "../sseNormalize";

// ---------------------------------------------------------------------------
// Regression: native turn_summary must produce a NONBLANK activity label.
//
// The backend serializes a traceforge turn_summary with snake_case payload
// keys; useSSE runs it through normalizeTFEvent (deep snake->camel) before the
// reducer. These tests drive that real path so they catch the blank-header bug
// (backend omitting activity_label + reducer writing undefined).
// ---------------------------------------------------------------------------

function turnSummaryEvent(payload: Record<string, unknown>): TFSessionEvent {
  return { kind: "turn.summary", session_id: "job-1", payload };
}

function dispatchNative(payload: Record<string, unknown>): void {
  const normalized = normalizeTFEvent(turnSummaryEvent(payload));
  useStore.getState().dispatchSSEEvent("turn.summary", normalized);
}

function activities(jobId = "job-1") {
  return useStore.getState().activityTimelines[jobId]?.activities ?? [];
}

beforeEach(() => {
  useStore.setState({ activityTimelines: {} });
});

describe("turn.summary reducer — native activity labels", () => {
  it("creates an activity group with the native activity_label", () => {
    dispatchNative({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      is_new_activity: true,
      activity_label: "Setting up environment",
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    expect(acts[0]?.label).toBe("Setting up environment");
    // The regression: the header must never be blank/undefined.
    expect(acts[0]?.label).toBeTruthy();
    expect(acts[0]?.steps).toHaveLength(1);
  });

  it("preserves the activity label across subsequent step updates", () => {
    // Activity update establishes the label.
    dispatchNative({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      is_new_activity: true,
      activity_label: "Setting up environment",
    });

    // Step update carries NO activity_label (a step's title is not the label).
    dispatchNative({
      turn_id: "step-1",
      title: "Reading config file",
      activity_id: "act-1",
      is_new_activity: false,
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    // Label preserved, not overwritten with undefined.
    expect(acts[0]?.label).toBe("Setting up environment");
    expect(acts[0]?.steps).toHaveLength(2);
    expect(acts[0]?.steps[1]?.title).toBe("Reading config file");
  });

  it("falls back to the turn title when activity_label is absent (never blank)", () => {
    // Defensive: even a payload missing activity_label must yield a nonblank
    // header rather than writing undefined.
    dispatchNative({
      turn_id: "act-1",
      title: "Investigating failure",
      activity_id: "act-1",
      is_new_activity: true,
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    expect(acts[0]?.label).toBe("Investigating failure");
    expect(acts[0]?.label).toBeTruthy();
  });
});
