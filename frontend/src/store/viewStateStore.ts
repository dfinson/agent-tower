/**
 * Persisted view state store.
 *
 * Stored in localStorage — separate from the main store to avoid serialising
 * the full transcript on every update.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

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
        set((s) => ({ lastSeenSeq: { ...s.lastSeenSeq, [jobId]: seq } })),
    }),
    { name: "codeplane-view-state" },
  ),
);
