/**
 * TraceForge SSE ingestion adapter.
 *
 * The backend serializes each `traceforge.SessionEvent` to the SSE wire as-is:
 *   - the SSE `event:` line is the dotted kind (e.g. "job.state_changed",
 *     "tool.call.completed", "permission.requested");
 *   - the SSE `data:` line is the full event envelope
 *     `{ id, kind, session_id, timestamp, payload, metadata }` where `payload`
 *     is the raw control-plane payload in **snake_case**.
 *
 * This module adapts that wire shape into the store's internal camelCase
 * domain model at the ingestion boundary (used by `useSSE`), so the store
 * handlers keep reading the camelCase fields they always have. It:
 *   1. deep-converts payload keys snake_case -> camelCase (`normalizeTFEvent`);
 *   2. injects the envelope-derived fields handlers expect (`jobId` from
 *      `session_id`, `timestamp`, `turnId` from `metadata.turn_id`);
 *   3. re-derives the job-state transitions the backend previously emitted as a
 *      secondary `job_state_changed` frame — those are now computed on the FE
 *      from the dotted kind (`deriveJobStateFrame`).
 *
 * There is no reverse (camel -> snake) path and no old-wire vocabulary: the
 * wire speaks TraceForge; this adapter is purely the FE's own domain mapping.
 */

/** Minimal shape of a serialized `traceforge.SessionEvent` on the SSE wire. */
export interface TFSessionEvent {
  id?: string;
  kind: string;
  session_id: string;
  timestamp?: string;
  payload?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
}

const SNAKE_SEGMENT = /_([a-z0-9])/g;

function snakeKeyToCamel(key: string): string {
  return key.replace(SNAKE_SEGMENT, (_m, c: string) => c.toUpperCase());
}

/**
 * Recursively convert object keys from snake_case to camelCase.
 *
 * - Only keys are transformed; values are left untouched (so a discriminator
 *   like `role: "agent_delta"` survives verbatim).
 * - Recurses through nested objects and arrays (transcript entries, approval
 *   actions, plan steps, diff hunks, symbols, ...).
 * - Idempotent: already-camel and single-word keys are unchanged.
 */
export function deepSnakeToCamel(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(deepSnakeToCamel);
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[snakeKeyToCamel(k)] = deepSnakeToCamel(v);
    }
    return out;
  }
  return value;
}

/**
 * Unwrap a TF event envelope into the camelCase payload the store handlers
 * consume, injecting `jobId`/`timestamp`/`turnId` from the envelope.
 */
export function normalizeTFEvent(ev: TFSessionEvent): Record<string, unknown> {
  const payload = deepSnakeToCamel(ev.payload ?? {}) as Record<string, unknown>;

  // `jobId` is authoritative from the envelope session id.
  payload.jobId = ev.session_id;

  if (payload.timestamp === undefined && ev.timestamp !== undefined) {
    payload.timestamp = ev.timestamp;
  }

  // turn_id lives on EventMetadata; carry it as camelCase `turnId` unless the
  // payload already provides one.
  const meta = ev.metadata;
  const metaTurnId = meta == null ? undefined : (meta as Record<string, unknown>).turn_id;
  if (payload.turnId === undefined && metaTurnId != null) {
    payload.turnId = metaTurnId;
  }

  return payload;
}

/** Dotted kinds that map directly to a single implied job state. */
const JOB_STATE_BY_KIND: Record<string, string> = {
  "job.created": "running",
  "job.canceled": "canceled",
  "job.review": "review",
  "job.completed": "completed",
  "job.failed": "failed",
};

/**
 * Re-derive the job-state transition the backend used to synthesize as a
 * secondary `job_state_changed` frame after certain primary events.
 *
 * Returns a `handleJobStateChanged`-shaped payload (`{ jobId, newState,
 * timestamp }`) or `null` when a kind implies no state change. `permission.*`
 * kinds derive their state from the resolution; batch permission kinds derive
 * nothing (they never drove a job-state frame).
 */
export function deriveJobStateFrame(
  kind: string,
  payload: Record<string, unknown>,
): Record<string, unknown> | null {
  const base = { jobId: payload.jobId, timestamp: payload.timestamp };

  if (kind === "permission.requested") {
    return { ...base, newState: "waiting_for_approval" };
  }
  if (kind === "permission.resolved") {
    return { ...base, newState: payload.resolution === "approved" ? "running" : "failed" };
  }

  const mapped = JOB_STATE_BY_KIND[kind];
  if (mapped) {
    return { ...base, newState: mapped };
  }
  return null;
}
