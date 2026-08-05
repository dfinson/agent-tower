import { describe, it, expect, beforeEach } from "vitest";
import { useStore } from "../index";
import { normalizeTFEvent } from "../sseNormalize";

/**
 * Wire-boundary regression for the activity-timeline group heading.
 *
 * The backend emits `turn.summary` from TraceForge's native `TitleUpdate`.
 * Activity-kind updates carry `activity_label` (TF's own title); step-kind
 * updates carry none. These tests drive raw snake_case TF wire frames through
 * the exact adapter `useSSE` uses (`normalizeTFEvent` -> `dispatchSSEEvent`), so
 * a label dropped anywhere along that path — or a synthetic label invented from
 * a step title — is caught. Native-only contract: a missing OR blank
 * `activity_label` means "no opinion" and never overwrites or fabricates.
 */

/** Feed a raw snake_case TF wire frame through the same adapter `useSSE` uses. */
function dispatchTF(payload: Record<string, unknown>) {
  const normalized = normalizeTFEvent({
    kind: "turn.summary",
    session_id: "job-1",
    timestamp: "2025-01-01T00:00:00Z",
    payload,
  });
  useStore.getState().dispatchSSEEvent("turn.summary", normalized);
}

function activities() {
  return useStore.getState().activityTimelines["job-1"]?.activities ?? [];
}

beforeEach(() => {
  useStore.setState({ activityTimelines: {} });
});

describe("turn.summary → activity timeline (wire boundary)", () => {
  it("gives the activity group a nonblank label from a native activity update", () => {
    dispatchTF({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      activity_label: "Setting up environment",
      is_new_activity: true,
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    expect(acts[0]?.label).toBe("Setting up environment");
    expect(acts[0]?.label).not.toBe("");
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

    const acts = activities();
    expect(acts).toHaveLength(1);
    expect(acts[0]?.label).toBe("Setting up environment");
    expect(acts[0]?.steps.map((s) => s.title)).toEqual([
      "Setting up environment",
      "Reading config file",
    ]);
  });

  it("keeps the label when a step update carries a blank activity_label", () => {
    dispatchTF({
      turn_id: "act-1",
      title: "Setting up environment",
      activity_id: "act-1",
      activity_label: "Setting up environment",
      is_new_activity: true,
    });
    // A blank activity_label is also "no opinion" — it must not erase the label.
    dispatchTF({
      turn_id: "step-2",
      title: "Writing tests",
      activity_id: "act-1",
      activity_label: "",
      is_new_activity: false,
    });

    const acts = activities();
    expect(acts).toHaveLength(1);
    expect(acts[0]?.label).toBe("Setting up environment");
    expect(acts[0]?.steps).toHaveLength(2);
  });

  it("does not fabricate an activity label from a leading step's title", () => {
    // A step arrives before any native activity update — no activity_label.
    dispatchTF({
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
    dispatchTF({
      turn_id: "s0",
      title: "Looking around",
      activity_id: "a0",
      is_new_activity: false,
    });
    // A real activity-kind update then opens a properly-labeled group.
    dispatchTF({
      turn_id: "act-1",
      title: "Fixing the bug",
      activity_id: "act-1",
      activity_label: "Fixing the bug",
      is_new_activity: true,
    });

    const acts = activities();
    expect(acts).toHaveLength(2);
    expect(acts[0]?.label).toBe(""); // leading step stays blank (no fabrication)
    expect(acts[1]?.label).toBe("Fixing the bug");
  });
});
