/**
 * Persisted view state store.
 *
 * Stored in localStorage — separate from the main store to avoid serialising
 * the full transcript on every update.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

/** Max entries kept in localStorage to avoid quota exhaustion. */
const MAX_ENTRIES = 500;

interface ViewStateStore {
  /** Last seen transcript sequence number per job — drives resume banner. */
  lastSeenSeq: Record<string, number>;

  setLastSeenSeq: (jobId: string, seq: number) => void;
}

export const useViewStateStore = create<ViewStateStore>()(
  persist(
    (set) => ({
      lastSeenSeq: {},

      setLastSeenSeq: (jobId, seq) =>
        set((s) => {
          const updated = { ...s.lastSeenSeq, [jobId]: seq };
          // Evict oldest entries if over limit (keys are insertion-ordered in modern JS engines)
          const keys = Object.keys(updated);
          if (keys.length > MAX_ENTRIES) {
            for (const k of keys.slice(0, keys.length - MAX_ENTRIES)) {
              delete updated[k];
            }
          }
          return { lastSeenSeq: updated };
        }),
    }),
    { name: "codeplane-view-state" },
  ),
);
