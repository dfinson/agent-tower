/**
 * Shared types for SSE event handlers.
 */

import type { AppState } from "../types";

export type SSEHandler = (
  state: AppState,
  payload: Record<string, unknown>,
  getFresh: () => AppState,
  eventType: string,
) => Partial<AppState> | null;

export type { AppState };
