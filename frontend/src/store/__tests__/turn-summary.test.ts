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

  it("keeps an established native label across omitted and blank step labels", () => {
    // Activity update establishes the native label.
    dispatchNative({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      is_new_activity: true,
      activity_label: "Setting up environment",
    });

    // Step update with the activity_label key OMITTED.
    dispatchNative({
      turn_id: "step-1",
      title: "Reading config file",
      activity_id: "act-1",
      is_new_activity: false,
    });

    // Step update with an explicit BLANK activity_label — also "no opinion".
    dispatchNative({
      turn_id: "step-2",
      title: "Writing tests",
      activity_id: "act-1",
      is_new_activity: false,
      activity_label: "",
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    // The established label survives both the omitted and the blank step label.
    expect(acts[0]?.label).toBe("Setting up environment");
    expect(acts[0]?.steps).toHaveLength(3);
  });

  it("does not fabricate an activity label from a leading step's title", () => {
    // A step arrives before any native activity update — no activity_label.
    dispatchNative({
      turn_id: "s0",
      title: "Looking around",
      activity_id: "a0",
      is_new_activity: false,
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    // Native-only: blank is acceptable until a native activity update; the step
    // title must NOT be promoted to the activity header.
    expect(acts[0]?.label).toBe("");
    expect(acts[0]?.label).not.toBe("Looking around");
  });

  it("adopts the native label once an activity update follows a leading step", () => {
    dispatchNative({
      turn_id: "s0",
      title: "Looking around",
      activity_id: "a0",
      is_new_activity: false,
    });
    // A real activity-kind update then opens a properly-labeled group.
    dispatchNative({
      turn_id: "act-1",
      title: "Fixing the bug",
      activity_id: "act-1",
      is_new_activity: true,
      activity_label: "Fixing the bug",
    });

    const acts = activities();
    expect(acts).toHaveLength(2);
    expect(acts[0]?.label).toBe(""); // leading step stays blank (no fabrication)
    expect(acts[1]?.label).toBe("Fixing the bug");
  });
});
