/**
 * Transcript, tool group summary, and log line SSE event handlers.
 */

import type { LogLine, TranscriptEntry } from "../types";
import type { SSEHandler, AppState } from "./types";

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

export function handleLogLine(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const entry: LogLine = {
    jobId,
    seq: payload.seq as number,
    timestamp: payload.timestamp as string,
    level: payload.level as string,
    message: payload.message as string,
    context: (payload.context as Record<string, unknown> | null) ?? null,
  };
  const existing = state.logs[jobId] ?? [];
  const updated = [...existing, entry];
  return {
    logs: { ...state.logs, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
  };
}

export function handleTranscriptUpdate(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const role = payload.role as string;

  // agent_delta: accumulate streaming text per turn, don't add to transcript
  if (role === "agent_delta") {
    const turnId = (payload.turnId as string | undefined) ?? "__default__";
    const key = `${jobId}:${turnId}`;
    const delta = (payload.content as string) ?? "";
    return {
      streamingMessages: {
        ...state.streamingMessages,
        [key]: (state.streamingMessages[key] ?? "") + delta,
      },
    };
  }

  // tool_output_delta: accumulate streaming tool output, don't add to transcript
  if (role === "tool_output_delta") {
    const toolCallId = (payload.toolCallId as string | undefined) ?? (payload.toolName as string | undefined) ?? "__tool__";
    const key = `${jobId}:${toolCallId}`;
    const chunk = (payload.content as string) ?? "";
    return {
      streamingToolOutput: {
        ...state.streamingToolOutput,
        [key]: (state.streamingToolOutput[key] ?? "") + chunk,
      },
    };
  }

  // reasoning_delta: accumulate streaming reasoning per turn, don't add to transcript
  if (role === "reasoning_delta") {
    const turnId = (payload.turnId as string | undefined) ?? "__default__";
    const key = `${jobId}:${turnId}`;
    const delta = (payload.content as string) ?? "";
    return {
      streamingReasoning: {
        ...state.streamingReasoning,
        [key]: (state.streamingReasoning[key] ?? "") + delta,
      },
    };
  }

  const entry: TranscriptEntry = {
    jobId,
    seq: payload.seq as number,
    timestamp: payload.timestamp as string,
    role,
    content: payload.content as string,
    title: payload.title as string | undefined,
    turnId: payload.turnId as string | undefined,
    toolName: payload.toolName as string | undefined,
    toolArgs: payload.toolArgs as string | undefined,
    toolResult: payload.toolResult as string | undefined,
    toolSuccess: payload.toolSuccess as boolean | undefined,
    toolIssue: payload.toolIssue as string | undefined,
    toolIntent: payload.toolIntent as string | undefined,
    toolTitle: payload.toolTitle as string | undefined,
    toolDisplay: payload.toolDisplay as string | undefined,
    toolDisplayFull: payload.toolDisplayFull as string | undefined,
    toolDurationMs: payload.toolDurationMs as number | undefined,
    toolVisibility: payload.toolVisibility as string | undefined,
  };
  const existing = state.transcript[jobId] ?? [];

  // When a tool_call arrives, replace any matching tool_running entry
  // (same toolName, and same turnId when both are present) so the
  // in-progress placeholder is superseded.
  let base = existing;
  if (entry.role === "tool_call") {
    const before = base.length;
    base = base.filter((e) => {
      if (e.role !== "tool_running" || e.toolName !== entry.toolName) return true;
      // If both entries have a turnId, they must match to be considered the same call.
      if (entry.turnId && e.turnId && entry.turnId !== e.turnId) return true;
      return false;
    });
    // If we replaced something, update both transcript and step index.
    if (base.length < before) {
      const updated = [...base, entry];

      return {
        transcript: { ...state.transcript, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
      };
    }
  }

  // Deduplicate: two SSE connections (global + job-scoped) may deliver
  // the same event; skip if identical role+content+timestamp already present.
  if (existing.some((e) => e.timestamp === entry.timestamp && e.role === entry.role && e.content === entry.content)) {
    return null;
  }
  const updated = [...existing, entry];

  // When a complete agent message arrives, clear streaming state for that turn.
  let streamingMessages = state.streamingMessages;
  if (entry.role === "agent") {
    const key = entry.turnId ? `${jobId}:${entry.turnId}` : `${jobId}:__default__`;
    if (key in streamingMessages) {
      streamingMessages = { ...streamingMessages };
      delete streamingMessages[key];
    }
  }

  // When a tool_call (completion) arrives, clear streaming tool output.
  let streamingToolOutput = state.streamingToolOutput;
  if (entry.role === "tool_call") {
    // Clear all streaming entries for this job (tool call IDs vary)
    const prefix = `${jobId}:`;
    const keys = Object.keys(streamingToolOutput).filter((k) => k.startsWith(prefix));
    if (keys.length > 0) {
      streamingToolOutput = { ...streamingToolOutput };
      for (const k of keys) delete streamingToolOutput[k];
    }
  }

  // When a complete reasoning message arrives, clear streaming reasoning for that turn.
  let streamingReasoning = state.streamingReasoning;
  if (entry.role === "reasoning") {
    const key = entry.turnId ? `${jobId}:${entry.turnId}` : `${jobId}:__default__`;
    if (key in streamingReasoning) {
      streamingReasoning = { ...streamingReasoning };
      delete streamingReasoning[key];
    }
  }

  return {
    transcript: { ...state.transcript, [jobId]: updated.length > 10_000 ? updated.slice(-10_000) : updated },
    streamingMessages,
    streamingToolOutput,
    streamingReasoning,
  };
}

export function handleToolGroupSummary(state: AppState, payload: Record<string, unknown>): Partial<AppState> | null {
  const jobId = payload.jobId as string;
  const turnId = payload.turnId as string;
  const summary = payload.summary as string;
  const entries = state.transcript[jobId];
  if (!entries) return null;
  let changed = false;
  const patched = entries.map((e) => {
    if (e.role === "tool_call" && e.turnId === turnId && e.toolGroupSummary !== summary) {
      changed = true;
      return { ...e, toolGroupSummary: summary };
    }
    return e;
  });
  if (!changed) return null;
  return { transcript: { ...state.transcript, [jobId]: patched } };
}

export const transcriptHandlers: Record<string, SSEHandler> = {
  log_line: handleLogLine,
  transcript_update: handleTranscriptUpdate,
  tool_group_summary: handleToolGroupSummary,
};
