import type { TranscriptEntry } from "../store";

function hasComparableSequence(entry: TranscriptEntry): entry is TranscriptEntry & { sequence: number } {
  return Number.isSafeInteger(entry.sequence);
}

export function transcriptIdentity(entry: TranscriptEntry): string | null {
  if (entry.eventId) return `event:${entry.eventId}`;
  return null;
}

export function sameTranscriptEntry(left: TranscriptEntry, right: TranscriptEntry): boolean {
  return Boolean(left.eventId && right.eventId && left.eventId === right.eventId);
}

export function mergeTranscriptEntries(
  historical: TranscriptEntry[],
  live: TranscriptEntry[],
): TranscriptEntry[] {
  const merged = [...historical];
  for (const entry of live) {
    if (!merged.some((candidate) => sameTranscriptEntry(candidate, entry))) {
      merged.push(entry);
    }
  }
  if (merged.every(hasComparableSequence)) {
    return [...merged].sort((left, right) => left.sequence! - right.sequence!);
  }
  return merged;
}

export function transcriptReactKey(entry: TranscriptEntry, index: number): string {
  return transcriptIdentity(entry) ?? `transcript:${index}`;
}
