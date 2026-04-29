"""
Context window snapshot size evaluation.

The StepTracker buffer keeps 10 entries (empirically validated). At step
close, it snapshots the last N entries into the event payload via `buf[-5:]`.
This snapshot is persisted and fed to LLM prompts (motivation, enrichment).

Research question: What is the right snapshot size N, given the buffer is 10?

We already know from the buffer size eval that:
  - Size 5:  85.0% file coverage, 61.0% motivation, ~632 tokens P90
  - Size 10: 92.5% file coverage, 79.4% motivation, ~1140 tokens P90

But those numbers measure "is the signal present in the window at all."
The snapshot has a different concern: what actually gets persisted and
sent to LLM prompts. The trade-offs are:

  - Larger snapshot = more context for enrichment LLM = better quality
  - Larger snapshot = more tokens per prompt = higher cost per enrichment call
  - Larger snapshot = larger DB rows = more storage

This experiment measures the *information density* of each entry position
in the buffer. Entry [-1] is the most recent (highest information), entry
[-10] is the oldest (most likely to be noise). We measure what each
position contributes to coverage — if positions [-6] through [-10] rarely
contain the signals we care about, there's no point persisting them.

Usage:
    python tools/context_snapshot_eval.py
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

EXCLUDED_ROLES = frozenset({"agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"})
CONTENT_MAX = 800

PROBLEM_WORDS = re.compile(
    r"bug|issue|vulnerab|missing|broken|fix|problem|error|fail|insecure|unsafe|"
    r"no validation|inject|should|needs? to|must|wrong|incorrect|smell|dead.code|"
    r"unused|duplicate|redundant|inconsistent|stale|outdated|hardcoded|hack|"
    r"todo|workaround|deprecated|leak|race.condition",
    re.IGNORECASE,
)

from eval_helpers import extract_file_identifiers as _extract_file_identifiers


def _entry_text(entry: dict) -> str:
    parts = [entry.get("content", ""), entry.get("tool_name", ""), entry.get("tool_args", "")]
    return " ".join(p for p in parts if p)


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    step_rows = conn.execute("""
        SELECT e.id AS event_id, e.job_id, e.payload
        FROM events e
        WHERE e.kind = 'StepCompleted'
        ORDER BY e.id ASC
    """).fetchall()

    # Only steps with file writes (file coverage is the primary signal)
    steps = []
    for row in step_rows:
        payload = json.loads(row["payload"])
        files_written = payload.get("files_written") or []
        if files_written:
            steps.append((row["event_id"], row["job_id"], payload))

    print(f"Steps with file writes: {len(steps)}")

    # Group by job for batch loading
    steps_by_job: dict[str, list[tuple]] = defaultdict(list)
    for eid, jid, payload in steps:
        steps_by_job[jid].append((eid, payload))

    # For each step, reconstruct the full 10-entry buffer, then measure
    # what each POSITION contributes.
    #
    # Position -1 = most recent entry (closest to the step close)
    # Position -10 = oldest entry in a size-10 buffer
    #
    # For each position, we track:
    #   - Does this specific entry contain a target file mention?
    #   - Does this specific entry contain problem language?
    #   - Does this specific entry contain agent reasoning?
    #   - What role is this entry?
    #   - How many chars?

    BUFFER_SIZE = 10

    # Per-position accumulators (1-indexed from most recent: pos 1 = [-1])
    position_file_mention = defaultdict(int)    # pos → count of steps where this pos has file mention
    position_motivation = defaultdict(int)       # pos → count with problem language
    position_reasoning = defaultdict(int)        # pos → count with agent reasoning
    position_role_counts = defaultdict(lambda: defaultdict(int))  # pos → role → count
    position_chars = defaultdict(list)           # pos → list of char counts
    position_available = defaultdict(int)        # pos → how many steps had this position available

    # Cumulative coverage at each snapshot size (1 through 10)
    # "If I snapshot [-N:], what coverage do I get?"
    snapshot_file_coverage = defaultdict(int)
    snapshot_motivation_coverage = defaultdict(int)
    snapshot_reasoning_coverage = defaultdict(int)
    snapshot_chars = defaultdict(list)

    total_steps = 0

    for job_id, job_steps in steps_by_job.items():
        transcript_rows = conn.execute("""
            SELECT id, payload FROM events
            WHERE job_id = ? AND kind = 'TranscriptUpdated'
            ORDER BY id ASC
        """, (job_id,)).fetchall()

        transcript_entries = []
        for tr in transcript_rows:
            tp = json.loads(tr["payload"])
            role = tp.get("role", "")
            if role in EXCLUDED_ROLES:
                continue
            entry = {
                "event_id": tr["id"],
                "role": role,
                "content": str(tp.get("content", ""))[:CONTENT_MAX],
            }
            t_name = tp.get("tool_name")
            if t_name:
                entry["tool_name"] = str(t_name)
                t_args = tp.get("tool_args")
                if t_args:
                    entry["tool_args"] = str(t_args)[:CONTENT_MAX]
            transcript_entries.append(entry)

        for step_event_id, payload in job_steps:
            preceding = [e for e in transcript_entries if e["event_id"] < step_event_id]
            if not preceding:
                continue

            files_written = payload.get("files_written") or []
            file_ids = _extract_file_identifiers(files_written)
            if not file_ids:
                continue

            # Take the last BUFFER_SIZE entries (simulating the ring buffer)
            buffer = preceding[-BUFFER_SIZE:]
            total_steps += 1

            # Analyze each position (1 = most recent, len(buffer) = oldest)
            for i, entry in enumerate(reversed(buffer)):
                pos = i + 1  # 1-indexed from most recent
                position_available[pos] += 1

                text = _entry_text(entry)
                chars = len(text)
                position_chars[pos].append(chars)
                position_role_counts[pos][entry.get("role", "unknown")] += 1

                has_file = any(fid in text for fid in file_ids)
                has_motivation = (
                    entry.get("role") in ("agent", "reasoning")
                    and bool(PROBLEM_WORDS.search(entry.get("content", "")))
                )
                has_reasoning = (
                    entry.get("role") == "agent"
                    and len(entry.get("content", "").strip()) > 20
                )

                if has_file:
                    position_file_mention[pos] += 1
                if has_motivation:
                    position_motivation[pos] += 1
                if has_reasoning:
                    position_reasoning[pos] += 1

            # Cumulative coverage at each snapshot size
            for snap_size in range(1, BUFFER_SIZE + 1):
                window = buffer[-snap_size:]
                combined_text = " ".join(_entry_text(e) for e in window)

                has_any_file = any(fid in combined_text for fid in file_ids)
                has_any_motivation = any(
                    e.get("role") in ("agent", "reasoning")
                    and bool(PROBLEM_WORDS.search(e.get("content", "")))
                    for e in window
                )
                has_any_reasoning = any(
                    e.get("role") == "agent" and len(e.get("content", "").strip()) > 20
                    for e in window
                )

                if has_any_file:
                    snapshot_file_coverage[snap_size] += 1
                if has_any_motivation:
                    snapshot_motivation_coverage[snap_size] += 1
                if has_any_reasoning:
                    snapshot_reasoning_coverage[snap_size] += 1
                snapshot_chars[snap_size].append(sum(len(_entry_text(e)) for e in window))

    conn.close()

    print(f"Steps analyzed: {total_steps}")
    print()

    # === Report 1: Per-position information density ===
    print("=" * 85)
    print("PER-POSITION INFORMATION DENSITY (position 1 = most recent entry)")
    print("=" * 85)
    print()
    print(f"{'Pos':>3}  {'Avail':>5}  {'File%':>6}  {'Motiv%':>7}  {'Agent%':>7}  "
          f"{'Chars P50':>9}  {'Top roles'}")
    print("-" * 85)

    for pos in range(1, BUFFER_SIZE + 1):
        avail = position_available[pos]
        if avail == 0:
            continue

        file_pct = position_file_mention[pos] / avail * 100
        motiv_pct = position_motivation[pos] / avail * 100
        reason_pct = position_reasoning[pos] / avail * 100

        chars = sorted(position_chars[pos])
        p50 = chars[len(chars) // 2] if chars else 0

        role_counts = position_role_counts[pos]
        top_roles = sorted(role_counts.items(), key=lambda x: -x[1])[:3]
        role_str = ", ".join(f"{r}:{c}" for r, c in top_roles)

        print(f"{pos:>3}  {avail:>5}  {file_pct:>5.1f}%  {motiv_pct:>6.1f}%  {reason_pct:>6.1f}%  "
              f"{p50:>9,}  {role_str}")

    print()

    # === Report 2: Cumulative snapshot coverage ===
    print("=" * 85)
    print("CUMULATIVE SNAPSHOT COVERAGE (snapshot = last N entries persisted)")
    print("=" * 85)
    print()
    print(f"{'Snap':>4}  {'File%':>6}  {'ΔFile':>6}  {'Motiv%':>7}  {'ΔMotiv':>7}  "
          f"{'Agent%':>7}  {'Chars P90':>9}  {'~Tok P90':>8}")
    print("-" * 85)

    prev_file = prev_motiv = prev_reason = 0
    for snap_size in range(1, BUFFER_SIZE + 1):
        file_pct = snapshot_file_coverage[snap_size] / total_steps * 100
        motiv_pct = snapshot_motivation_coverage[snap_size] / total_steps * 100
        reason_pct = snapshot_reasoning_coverage[snap_size] / total_steps * 100

        chars = sorted(snapshot_chars[snap_size])
        n = len(chars)
        p90 = chars[int(n * 0.90)] if n else 0
        tok_p90 = p90 // 4

        df = file_pct - prev_file
        dm = motiv_pct - prev_motiv

        print(f"{snap_size:>4}  {file_pct:>5.1f}%  {df:>+5.1f}%  {motiv_pct:>6.1f}%  {dm:>+6.1f}%  "
              f"{reason_pct:>6.1f}%  {p90:>9,}  {tok_p90:>8,}")

        prev_file = file_pct
        prev_motiv = motiv_pct
        prev_reason = reason_pct

    print()
    print("INTERPRETATION:")
    print("  Position density: which entries carry the most signal?")
    print("  If position 6-10 rarely contain file mentions or motivation,")
    print("  persisting them wastes storage and tokens for no coverage gain.")
    print()
    print("  Cumulative coverage: what's the cost/benefit of each additional")
    print("  entry in the snapshot? The current snapshot is [-5:] (5 entries).")
    print("  Compare coverage at 5 vs 7 vs 10 to see what's left on the table.")


if __name__ == "__main__":
    run()
