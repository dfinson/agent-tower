import type { TranscriptEntry } from "../store";

function hasCanonicalSequence(entry: TranscriptEntry): entry is TranscriptEntry & { sequence: number } {
  return Number.isSafeInteger(entry.sequence) && entry.sequence! > 0;
}

export function transcriptIdentity(entry: TranscriptEntry): string | null {
  if (entry.eventId) return `event:${entry.eventId}`;
  if (hasCanonicalSequence(entry)) return `sequence:${entry.sequence}`;
  return null;
}

function semanticIdentity(entry: TranscriptEntry): string {
  return [
    entry.kind,
    entry.timestamp,
    entry.turnId ?? "",
    entry.toolCallId ?? "",
    entry.toolName ?? "",
    entry.content ?? "",
    entry.arguments ?? "",
    entry.result ?? "",
  ].join("\u001f");
}

export function sameTranscriptEntry(left: TranscriptEntry, right: TranscriptEntry): boolean {
  if (left.eventId && right.eventId) return left.eventId === right.eventId;
  if (hasCanonicalSequence(left) && hasCanonicalSequence(right)) {
    return left.sequence === right.sequence;
  }
  return semanticIdentity(left) === semanticIdentity(right);
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
  if (merged.every(hasCanonicalSequence)) {
    return [...merged].sort((left, right) => left.sequence! - right.sequence!);
  }
  return merged;
}

export function transcriptReactKey(entry: TranscriptEntry, index: number): string {
  return transcriptIdentity(entry) ?? `${semanticIdentity(entry)}\u001f${index}`;
}
