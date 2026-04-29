"""
Context window buffer size evaluation — Phase 1: Coverage measurement.

Research question: What is the relationship between preceding_context buffer
size and coverage of causal signals? Is there an inflection point?

For every step_completed event, we replay the TranscriptUpdated events that
preceded it and simulate the StepTracker ring buffer at various sizes. For
each size we measure:

  1. Target file coverage — does the window mention any file this step wrote?
  2. Motivation coverage — does it contain problem-identification language?
  3. Agent reasoning coverage — does it contain an agent message with substance?
  4. Explicit intent coverage — does it contain a report_intent tool call?

We also measure total chars per window size (token budget proxy).

The buffer filtering matches StepTracker exactly: excludes agent_delta,
reasoning_delta, tool_output_delta, tool_running roles. Content is capped
at _CONTENT_MAX=800 per entry (matching production).

Usage:
    python tools/context_window_eval.py
"""

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

# Buffer sizes to test
WINDOW_SIZES = [3, 5, 7, 8, 9, 10, 11, 12, 13, 15, 20, 30]

# Match production StepTracker filtering exactly
EXCLUDED_ROLES = frozenset({"agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"})

# Match production content truncation
CONTENT_MAX = 800

# From motivation_distance.py — language that indicates the agent identified
# a problem or reason for action
PROBLEM_WORDS = re.compile(
    r"bug|issue|vulnerab|missing|broken|fix|problem|error|fail|insecure|unsafe|"
    r"no validation|inject|should|needs? to|must|wrong|incorrect|smell|dead.code|"
    r"unused|duplicate|redundant|inconsistent|stale|outdated|hardcoded|hack|"
    r"todo|workaround|deprecated|leak|race.condition",
    re.IGNORECASE,
)

from eval_helpers import extract_file_identifiers as _extract_file_identifiers


def _build_entry_text(entry: dict) -> str:
    """Concatenate all searchable text from a transcript buffer entry."""
    parts = [
        entry.get("content", ""),
        entry.get("tool_name", ""),
        entry.get("tool_args", ""),
    ]
    return " ".join(p for p in parts if p)


def _has_file_mention(entries: list[dict], file_ids: set[str]) -> bool:
    """Does any entry mention any of the target file identifiers?"""
    for entry in entries:
        text = _build_entry_text(entry)
        for fid in file_ids:
            if fid in text:
                return True
    return False


def _has_problem_language(entries: list[dict]) -> bool:
    """Does any agent/reasoning entry contain problem-identification language?"""
    for entry in entries:
        role = entry.get("role", "")
        if role in ("agent", "reasoning"):
            if PROBLEM_WORDS.search(entry.get("content", "")):
                return True
    return False


def _has_agent_reasoning(entries: list[dict]) -> bool:
    """Does any entry contain a substantive agent message (>20 chars)?"""
    for entry in entries:
        if entry.get("role") == "agent":
            content = entry.get("content", "")
            if len(content.strip()) > 20:
                return True
    return False


def _has_explicit_intent(entries: list[dict]) -> bool:
    """Does any entry contain a report_intent tool call?"""
    for entry in entries:
        if entry.get("tool_name") == "report_intent":
            return True
    return False


def _total_chars(entries: list[dict]) -> int:
    """Total character count across all entries."""
    return sum(len(_build_entry_text(e)) for e in entries)


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Load all step_completed events
    step_rows = conn.execute("""
        SELECT e.id AS event_id, e.job_id, e.payload
        FROM events e
        WHERE e.kind = 'StepCompleted'
        ORDER BY e.id ASC
    """).fetchall()

    print(f"Total step_completed events: {len(step_rows)}")

    # Pre-filter to steps with file writes (most interesting for coverage)
    # but also keep explore-only steps for the full picture
    steps_with_writes = []
    steps_explore_only = []

    for row in step_rows:
        payload = json.loads(row["payload"])
        files_written = payload.get("files_written") or []
        files_read = payload.get("files_read") or []
        if files_written:
            steps_with_writes.append((row["event_id"], row["job_id"], payload))
        elif files_read:
            steps_explore_only.append((row["event_id"], row["job_id"], payload))

    print(f"Steps with file writes: {len(steps_with_writes)}")
    print(f"Steps with reads only: {len(steps_explore_only)}")
    print()

    # For each step, reconstruct the buffer at each window size
    # and measure coverage metrics.
    #
    # Metrics indexed by (window_size, step_category)
    max_window = max(WINDOW_SIZES)

    # Accumulators per window size
    results: dict[int, dict[str, list]] = {
        ws: {
            "file_coverage": [],       # bool per step-with-writes
            "motivation_coverage": [],  # bool per all steps
            "reasoning_coverage": [],   # bool per all steps
            "intent_coverage": [],      # bool per all steps
            "total_chars": [],          # int per all steps
        }
        for ws in WINDOW_SIZES
    }

    all_steps = (
        [(eid, jid, p, "write") for eid, jid, p in steps_with_writes]
        + [(eid, jid, p, "explore") for eid, jid, p in steps_explore_only]
    )

    # Process in job batches to avoid per-step queries
    steps_by_job: dict[str, list[tuple]] = defaultdict(list)
    for eid, jid, payload, category in all_steps:
        steps_by_job[jid].append((eid, payload, category))

    processed = 0
    total = len(all_steps)

    for job_id, job_steps in steps_by_job.items():
        # Load all transcript events for this job, ordered by event ID
        transcript_rows = conn.execute("""
            SELECT id, payload FROM events
            WHERE job_id = ? AND kind = 'TranscriptUpdated'
            ORDER BY id ASC
        """, (job_id,)).fetchall()

        # Parse into entries with their event IDs
        transcript_entries = []
        for tr in transcript_rows:
            tp = json.loads(tr["payload"])
            role = tp.get("role", "")
            # Match StepTracker's filtering
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

        for step_event_id, payload, category in job_steps:
            # Find all transcript entries preceding this step_completed event
            preceding = [e for e in transcript_entries if e["event_id"] < step_event_id]

            if not preceding:
                continue

            files_written = payload.get("files_written") or []
            files_read = payload.get("files_read") or []
            file_ids = _extract_file_identifiers(files_written + files_read)

            # Test each window size
            for ws in WINDOW_SIZES:
                window = preceding[-ws:]  # last N entries

                r = results[ws]

                # File coverage — only measured for write steps
                if category == "write" and file_ids:
                    write_file_ids = _extract_file_identifiers(files_written)
                    r["file_coverage"].append(_has_file_mention(window, write_file_ids))

                r["motivation_coverage"].append(_has_problem_language(window))
                r["reasoning_coverage"].append(_has_agent_reasoning(window))
                r["intent_coverage"].append(_has_explicit_intent(window))
                r["total_chars"].append(_total_chars(window))

            processed += 1
            if processed % 100 == 0:
                print(f"  Processed {processed}/{total} steps...", file=sys.stderr)

    conn.close()

    # Report
    print("=" * 90)
    print("CONTEXT WINDOW BUFFER SIZE EVALUATION — Phase 1: Coverage")
    print("=" * 90)
    print()
    print(f"Steps analyzed: {processed} ({len(steps_with_writes)} with writes, "
          f"{len(steps_explore_only)} explore-only)")
    print()

    # Coverage table
    print("COVERAGE BY WINDOW SIZE")
    print("-" * 90)
    header = f"{'Size':>4}  {'File%':>6}  {'Motiv%':>6}  {'Agent%':>6}  {'Intent%':>7}  "
    header += f"{'Chars P50':>9}  {'Chars P90':>9}  {'Chars P95':>9}  {'~Tokens P90':>11}"
    print(header)
    print("-" * 90)

    for ws in WINDOW_SIZES:
        r = results[ws]

        file_pct = (sum(r["file_coverage"]) / len(r["file_coverage"]) * 100) if r["file_coverage"] else 0
        motiv_pct = (sum(r["motivation_coverage"]) / len(r["motivation_coverage"]) * 100) if r["motivation_coverage"] else 0
        reason_pct = (sum(r["reasoning_coverage"]) / len(r["reasoning_coverage"]) * 100) if r["reasoning_coverage"] else 0
        intent_pct = (sum(r["intent_coverage"]) / len(r["intent_coverage"]) * 100) if r["intent_coverage"] else 0

        chars = sorted(r["total_chars"])
        n = len(chars)
        p50 = chars[n // 2] if n else 0
        p90 = chars[int(n * 0.90)] if n else 0
        p95 = chars[int(n * 0.95)] if n else 0
        tokens_p90 = p90 // 4  # rough estimate

        print(f"{ws:>4}  {file_pct:>5.1f}%  {motiv_pct:>5.1f}%  {reason_pct:>5.1f}%  {intent_pct:>6.1f}%  "
              f"{p50:>9,}  {p90:>9,}  {p95:>9,}  {tokens_p90:>11,}")

    print()

    # Marginal gain table
    print("MARGINAL GAIN PER ADDITIONAL ENTRY (vs previous size)")
    print("-" * 70)
    print(f"{'Size':>4}  {'ΔFile%':>7}  {'ΔMotiv%':>8}  {'ΔAgent%':>8}  {'ΔIntent%':>9}")
    print("-" * 70)

    prev = None
    for ws in WINDOW_SIZES:
        r = results[ws]
        file_pct = (sum(r["file_coverage"]) / len(r["file_coverage"]) * 100) if r["file_coverage"] else 0
        motiv_pct = (sum(r["motivation_coverage"]) / len(r["motivation_coverage"]) * 100) if r["motivation_coverage"] else 0
        reason_pct = (sum(r["reasoning_coverage"]) / len(r["reasoning_coverage"]) * 100) if r["reasoning_coverage"] else 0
        intent_pct = (sum(r["intent_coverage"]) / len(r["intent_coverage"]) * 100) if r["intent_coverage"] else 0

        if prev is not None:
            df = file_pct - prev[0]
            dm = motiv_pct - prev[1]
            dr = reason_pct - prev[2]
            di = intent_pct - prev[3]
            # Normalize per entry added
            entries_added = ws - prev[4]
            print(f"{ws:>4}  {df:>+6.1f}%  {dm:>+7.1f}%  {dr:>+7.1f}%  {di:>+8.1f}%"
                  f"    ({entries_added} entries added)")

        prev = (file_pct, motiv_pct, reason_pct, intent_pct, ws)

    print()

    print("NOTE: Token estimates use rough 4 chars/token. Actual varies by model.")
    print()
    print("INTERPRETATION GUIDE:")
    print("  - File%: Of steps with file writes, how many have the target file")
    print("    mentioned in the context window? Higher = the LLM knows what file")
    print("    is being discussed.")
    print("  - Motiv%: Of all steps, how many have problem-identification language")
    print("    in the window? Higher = the LLM can explain WHY the action was taken.")
    print("  - Agent%: Of all steps, how many have a substantive agent message in")
    print("    the window? Higher = the LLM sees the agent's own reasoning.")
    print("  - Intent%: Of all steps, how many have an explicit report_intent call?")
    print("    This depends on the SDK providing structured intent — low values are")
    print("    expected.")
    print()
    print("  Look for: where marginal gains drop below ~1-2% per entry added.")
    print("  That's the inflection point — more entries add noise, not signal.")


if __name__ == "__main__":
    run()
