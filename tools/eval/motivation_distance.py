"""
How far back do you have to go to find the motivation for a write action?

For each file_write span, walk backwards through the transcript to find the
first event that mentions the target file by name. Measure the distance in:
  - Number of distinct turn_ids (logical turns)
  - Number of transcript events

Also check: where does problem-identification language first appear relative
to the write?
"""
import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

PROBLEM_WORDS = re.compile(
    r"bug|issue|vulnerab|missing|broken|fix|problem|error|fail|insecure|unsafe|"
    r"no validation|inject|should|needs? to|must|wrong|incorrect|smell|dead.code|"
    r"unused|duplicate|redundant|inconsistent|stale|outdated|hardcoded|hack|"
    r"todo|workaround|deprecated|leak|race.condition|unsafe",
    re.IGNORECASE,
)


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get all file_write spans with turn_id
    writes = conn.execute("""
        SELECT s.id, s.job_id, s.name, s.turn_id, s.tool_target, s.tool_args_json
        FROM job_telemetry_spans s
        WHERE s.turn_id IS NOT NULL
          AND s.span_type = 'tool'
          AND s.tool_category = 'file_write'
          AND s.tool_target IS NOT NULL AND s.tool_target != ''
    """).fetchall()

    # Metrics collectors
    target_mention_distances = []  # turns back to first mention of target file
    problem_lang_distances = []    # turns back to first problem-identification language
    no_target_mention = 0
    no_problem_lang = 0

    for wr in writes:
        target = wr["tool_target"] or ""
        # Extract multiple possible file identifiers
        target_parts = set()
        if "/" in target:
            target_parts.add(target.rsplit("/", 1)[-1])  # basename
        if target:
            target_parts.add(target.split("/")[-1].split(".")[0])  # stem
        # Also try extracting from tool_args
        try:
            args = json.loads(wr["tool_args_json"]) if wr["tool_args_json"] else {}
            for key in ("filePath", "file_path", "path", "file"):
                if key in args and "/" in str(args[key]):
                    target_parts.add(str(args[key]).rsplit("/", 1)[-1])
        except Exception:
            pass  # malformed tool_args_json — skip path extraction
        target_parts.discard("")

        if not target_parts:
            continue

        # Get first event ID for this write's turn
        first_eid = conn.execute("""
            SELECT MIN(id) FROM events
            WHERE job_id = ? AND kind = 'TranscriptUpdated'
              AND json_extract(payload, '$.turn_id') = ?
        """, (wr["job_id"], wr["turn_id"])).fetchone()[0]
        if not first_eid:
            continue

        # Get preceding transcript events (reasoning + agent + tool_call), ordered newest first
        preceding = conn.execute("""
            SELECT
                id,
                json_extract(payload, '$.turn_id') AS prev_turn_id,
                json_extract(payload, '$.role') AS role,
                json_extract(payload, '$.content') AS content,
                json_extract(payload, '$.tool_name') AS tool_name,
                json_extract(payload, '$.tool_args') AS tool_args
            FROM events
            WHERE job_id = ?
              AND kind = 'TranscriptUpdated'
              AND id < ?
            ORDER BY id DESC
            LIMIT 200
        """, (wr["job_id"], first_eid)).fetchall()

        if not preceding:
            continue

        # Build ordered distinct turn_ids (newest first)
        seen_turns = []
        seen_set = set()
        for ev in preceding:
            tid = ev["prev_turn_id"]
            if tid and tid not in seen_set:
                seen_set.add(tid)
                seen_turns.append(tid)

        # Find: how many turns back until target file is mentioned?
        found_target_at_turn = None
        found_problem_at_turn = None

        for ev in preceding:
            tid = ev["prev_turn_id"]
            if not tid:
                continue
            turn_distance = seen_turns.index(tid) + 1 if tid in seen_turns else len(seen_turns)

            content = (ev["content"] or "") + " " + (ev["tool_name"] or "") + " " + (ev["tool_args"] or "")

            # Check for target file mention
            if found_target_at_turn is None:
                for part in target_parts:
                    if part in content:
                        found_target_at_turn = turn_distance
                        break

            # Check for problem-identification language
            if found_problem_at_turn is None:
                if ev["role"] in ("reasoning", "agent") and PROBLEM_WORDS.search(content):
                    found_problem_at_turn = turn_distance

        if found_target_at_turn is not None:
            target_mention_distances.append(found_target_at_turn)
        else:
            no_target_mention += 1

        if found_problem_at_turn is not None:
            problem_lang_distances.append(found_problem_at_turn)
        else:
            no_problem_lang += 1

    conn.close()

    # Report
    print(f"Total file_write spans analyzed: {len(writes)}")
    print()

    def report(name, distances, no_count):
        if not distances:
            print(f"{name}: no data")
            return
        distances.sort()
        n = len(distances)
        print(f"{name}:")
        print(f"  Found in: {n}/{n + no_count} writes ({n / (n + no_count) * 100:.0f}%)")
        print(f"  Not found: {no_count}")
        print(f"  Min:    {min(distances)} turns back")
        print(f"  P25:    {distances[int(n * 0.25)]} turns back")
        print(f"  Median: {distances[n // 2]} turns back")
        print(f"  P75:    {distances[int(n * 0.75)]} turns back")
        print(f"  P90:    {distances[int(n * 0.90)]} turns back")
        print(f"  P95:    {distances[int(n * 0.95)]} turns back")
        print(f"  Max:    {max(distances)} turns back")
        print()

        # Distribution histogram
        buckets = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for label, lo, hi in [("6-10", 6, 10), ("11-20", 11, 20), ("21+", 21, 999)]:
            buckets[label] = 0
        for d in distances:
            if d <= 5:
                buckets[d] = buckets.get(d, 0) + 1
            elif d <= 10:
                buckets["6-10"] = buckets.get("6-10", 0) + 1
            elif d <= 20:
                buckets["11-20"] = buckets.get("11-20", 0) + 1
            else:
                buckets["21+"] = buckets.get("21+", 0) + 1

        print(f"  Distribution:")
        for label in [1, 2, 3, 4, 5, "6-10", "11-20", "21+"]:
            count = buckets.get(label, 0)
            pct = count / n * 100
            bar = "█" * int(pct / 2)
            print(f"    {str(label):>5} turns back: {count:>4} ({pct:>5.1f}%) {bar}")
        print()

    report("Distance to first mention of target file", target_mention_distances, no_target_mention)
    report("Distance to first problem-identification language", problem_lang_distances, no_problem_lang)


if __name__ == "__main__":
    run()
