"""
Combined measurement of remaining magic numbers:

1. Prompt truncations — do [:300], [:500], [:1500] ever fire?
2. Title/label lengths — what's the actual distribution?
3. _MAX_FILES_PER_STEP — how close do we get?
4. LLM timeouts — what are actual response times?

Usage:
    python tools/remaining_numbers_eval.py
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # =====================================================================
    # 1. Agent message lengths (feeds into [:300] and [:500] truncations)
    # =====================================================================
    print("=" * 80)
    print("1. AGENT MESSAGE SIZES (do prompt truncations fire?)")
    print("=" * 80)
    print()

    # Agent messages from step_completed payloads (what ProgressTrackingService sees)
    step_msgs = conn.execute("""
        SELECT json_extract(payload, '$.agent_message') as msg
        FROM events WHERE kind = 'StepCompleted'
        AND json_extract(payload, '$.agent_message') IS NOT NULL
    """).fetchall()

    msg_sizes = sorted(len(r["msg"]) for r in step_msgs if r["msg"])
    if msg_sizes:
        n = len(msg_sizes)
        print(f"Agent messages from step_completed: {n}")
        print(f"  P50: {msg_sizes[n//2]:,} chars")
        print(f"  P75: {msg_sizes[int(n*0.75)]:,} chars")
        print(f"  P90: {msg_sizes[int(n*0.90)]:,} chars")
        print(f"  P95: {msg_sizes[int(n*0.95)]:,} chars")
        print(f"  Max: {msg_sizes[-1]:,} chars")
        print()
        for threshold in [300, 500, 1000, 1500, 2000]:
            over = sum(1 for s in msg_sizes if s > threshold)
            print(f"  >{threshold:,}: {over}/{n} ({over/n*100:.1f}%)")
        print()
        print("  [:300] in classify prompt — fires on how many messages?")
        print(f"    {sum(1 for s in msg_sizes if s > 300)}/{n} = {sum(1 for s in msg_sizes if s > 300)/n*100:.1f}%")
        print(f"  [:500] in _MSG_MAX — fires on how many?")
        print(f"    {sum(1 for s in msg_sizes if s > 500)}/{n} = {sum(1 for s in msg_sizes if s > 500)/n*100:.1f}%")
    print()

    # Job prompts (feeds into [:500] task truncation in plan inference)
    job_prompts = conn.execute("""
        SELECT prompt FROM jobs WHERE prompt IS NOT NULL AND prompt != ''
    """).fetchall()
    prompt_sizes = sorted(len(r["prompt"]) for r in job_prompts)
    if prompt_sizes:
        n = len(prompt_sizes)
        print(f"Job prompts: {n}")
        print(f"  P50: {prompt_sizes[n//2]:,} chars")
        print(f"  P90: {prompt_sizes[int(n*0.90)]:,} chars")
        print(f"  P95: {prompt_sizes[int(n*0.95)]:,} chars")
        print(f"  Max: {prompt_sizes[-1]:,} chars")
        for threshold in [300, 500, 1000]:
            over = sum(1 for s in prompt_sizes if s > threshold)
            print(f"  >{threshold}: {over}/{n} ({over/n*100:.1f}%)")
    print()

    # preceding_context from step_completed (feeds into [:1500])
    ctx_rows = conn.execute("""
        SELECT json_extract(payload, '$.preceding_context') as ctx
        FROM events WHERE kind = 'StepCompleted'
        AND json_extract(payload, '$.preceding_context') IS NOT NULL
    """).fetchall()
    ctx_sizes = sorted(len(r["ctx"]) for r in ctx_rows if r["ctx"])
    if ctx_sizes:
        n = len(ctx_sizes)
        print(f"Preceding context from step_completed: {n}")
        print(f"  P50: {ctx_sizes[n//2]:,} chars")
        print(f"  P90: {ctx_sizes[int(n*0.90)]:,} chars")
        print(f"  P95: {ctx_sizes[int(n*0.95)]:,} chars")
        print(f"  Max: {ctx_sizes[-1]:,} chars")
        for threshold in [1000, 1500, 2000, 3000]:
            over = sum(1 for s in ctx_sizes if s > threshold)
            print(f"  >{threshold:,}: {over}/{n} ({over/n*100:.1f}%)")
    print()

    # =====================================================================
    # 2. Title and label lengths from generated events
    # =====================================================================
    print("=" * 80)
    print("2. GENERATED TITLE/LABEL LENGTH DISTRIBUTIONS")
    print("=" * 80)
    print()

    # Turn titles from turn_summary events
    title_rows = conn.execute("""
        SELECT json_extract(payload, '$.title') as title
        FROM events WHERE kind = 'TurnSummary'
        AND json_extract(payload, '$.title') IS NOT NULL
    """).fetchall()
    title_sizes = sorted(len(r["title"]) for r in title_rows if r["title"])
    if title_sizes:
        n = len(title_sizes)
        print(f"Turn titles (from TurnSummary events): {n}")
        print(f"  P50: {title_sizes[n//2]} chars")
        print(f"  P75: {title_sizes[int(n*0.75)]} chars")
        print(f"  P90: {title_sizes[int(n*0.90)]} chars")
        print(f"  P95: {title_sizes[int(n*0.95)]} chars")
        print(f"  Max: {title_sizes[-1]} chars")
        for threshold in [40, 50, 60, 70, 80, 100]:
            over = sum(1 for s in title_sizes if s > threshold)
            print(f"  >{threshold}: {over}/{n} ({over/n*100:.1f}%)")
        print()
        # Word count distribution
        word_counts = sorted(len(r["title"].split()) for r in title_rows if r["title"])
        n = len(word_counts)
        print(f"  Word counts: P50={word_counts[n//2]}, P90={word_counts[int(n*0.90)]}, "
              f"P95={word_counts[int(n*0.95)]}, Max={word_counts[-1]}")
    print()

    # Plan step labels
    label_rows = conn.execute("""
        SELECT json_extract(payload, '$.label') as label
        FROM events WHERE kind = 'PlanStepUpdated'
        AND json_extract(payload, '$.label') IS NOT NULL
    """).fetchall()
    # Deduplicate (same label emitted many times)
    seen_labels = set()
    unique_labels = []
    for r in label_rows:
        if r["label"] and r["label"] not in seen_labels:
            seen_labels.add(r["label"])
            unique_labels.append(r["label"])
    label_sizes = sorted(len(l) for l in unique_labels)
    if label_sizes:
        n = len(label_sizes)
        print(f"Plan step labels (unique): {n}")
        print(f"  P50: {label_sizes[n//2]} chars")
        print(f"  P75: {label_sizes[int(n*0.75)]} chars")
        print(f"  P90: {label_sizes[int(n*0.90)]} chars")
        print(f"  P95: {label_sizes[int(n*0.95)]} chars")
        print(f"  Max: {label_sizes[-1]} chars")
        for threshold in [40, 50, 60, 70, 80]:
            over = sum(1 for s in label_sizes if s > threshold)
            print(f"  >{threshold}: {over}/{n} ({over/n*100:.1f}%)")
        print()
        word_counts = sorted(len(l.split()) for l in unique_labels)
        n = len(word_counts)
        print(f"  Word counts: P50={word_counts[n//2]}, P90={word_counts[int(n*0.90)]}, "
              f"P95={word_counts[int(n*0.95)]}, Max={word_counts[-1]}")
    print()

    # Activity labels
    act_rows = conn.execute("""
        SELECT DISTINCT json_extract(payload, '$.activity_label') as label
        FROM events WHERE kind = 'TurnSummary'
        AND json_extract(payload, '$.activity_label') IS NOT NULL
    """).fetchall()
    act_sizes = sorted(len(r["label"]) for r in act_rows if r["label"])
    if act_sizes:
        n = len(act_sizes)
        print(f"Activity labels (unique): {n}")
        print(f"  P50: {act_sizes[n//2]} chars, P90: {act_sizes[int(n*0.90)]} chars, Max: {act_sizes[-1]} chars")
        for threshold in [60, 80, 100]:
            over = sum(1 for s in act_sizes if s > threshold)
            print(f"  >{threshold}: {over}/{n} ({over/n*100:.1f}%)")
    print()

    # =====================================================================
    # 3. Files per step
    # =====================================================================
    print("=" * 80)
    print("3. FILES PER STEP (is _MAX_FILES_PER_STEP=200 ever close?)")
    print("=" * 80)
    print()

    file_counts_read: list[int] = []
    file_counts_written: list[int] = []
    file_counts_total: list[int] = []

    step_rows = conn.execute("""
        SELECT payload FROM events WHERE kind = 'StepCompleted'
    """).fetchall()
    for r in step_rows:
        p = json.loads(r["payload"])
        fr = len(p.get("files_read") or [])
        fw = len(p.get("files_written") or [])
        file_counts_read.append(fr)
        file_counts_written.append(fw)
        file_counts_total.append(fr + fw)

    for name, counts in [("files_read", file_counts_read),
                          ("files_written", file_counts_written),
                          ("total files", file_counts_total)]:
        counts_sorted = sorted(counts)
        n = len(counts_sorted)
        if n == 0:
            continue
        print(f"{name}: {n} steps")
        print(f"  P50: {counts_sorted[n//2]}, P75: {counts_sorted[int(n*0.75)]}, "
              f"P90: {counts_sorted[int(n*0.90)]}, P95: {counts_sorted[int(n*0.95)]}, "
              f"P99: {counts_sorted[int(n*0.99)]}, Max: {counts_sorted[-1]}")
        for threshold in [10, 20, 50, 100, 150, 200]:
            over = sum(1 for c in counts if c >= threshold)
            if over > 0:
                print(f"  >={threshold}: {over} steps ({over/n*100:.1f}%)")
        print()

    # Note: these counts are AFTER the [:20] truncation in the event payload
    # So the real max could be higher — check step table directly
    step_db_rows = conn.execute("""
        SELECT files_read, files_written FROM steps
        WHERE files_read IS NOT NULL OR files_written IS NOT NULL
    """).fetchall()
    if step_db_rows:
        db_read_counts = []
        db_write_counts = []
        for r in step_db_rows:
            fr = json.loads(r["files_read"]) if r["files_read"] else []
            fw = json.loads(r["files_written"]) if r["files_written"] else []
            db_read_counts.append(len(fr))
            db_write_counts.append(len(fw))
        db_read_sorted = sorted(db_read_counts)
        db_write_sorted = sorted(db_write_counts)
        n = len(db_read_sorted)
        print(f"From steps table (persisted, subject to [:20] truncation):")
        print(f"  files_read max: {db_read_sorted[-1]}, files_written max: {db_write_sorted[-1]}")
        capped_read = sum(1 for c in db_read_counts if c == 20)
        capped_write = sum(1 for c in db_write_counts if c == 20)
        print(f"  Exactly 20 files_read (possibly capped): {capped_read}")
        print(f"  Exactly 20 files_written (possibly capped): {capped_write}")
    print()

    # =====================================================================
    # 4. LLM response times (sister session)
    # =====================================================================
    print("=" * 80)
    print("4. LLM RESPONSE TIMES (are timeout=10/15 ever hit?)")
    print("=" * 80)
    print()

    # Sister session calls are LLM spans with specific patterns
    llm_rows = conn.execute("""
        SELECT name, duration_ms FROM job_telemetry_spans
        WHERE span_type = 'llm' AND duration_ms IS NOT NULL
        ORDER BY duration_ms ASC
    """).fetchall()
    if llm_rows:
        durations = [r["duration_ms"] for r in llm_rows]
        n = len(durations)
        print(f"Total LLM spans: {n}")
        print(f"  P50: {durations[n//2]:,}ms ({durations[n//2]/1000:.1f}s)")
        print(f"  P75: {durations[int(n*0.75)]:,}ms ({durations[int(n*0.75)]/1000:.1f}s)")
        print(f"  P90: {durations[int(n*0.90)]:,}ms ({durations[int(n*0.90)]/1000:.1f}s)")
        print(f"  P95: {durations[int(n*0.95)]:,}ms ({durations[int(n*0.95)]/1000:.1f}s)")
        print(f"  P99: {durations[int(n*0.99)]:,}ms ({durations[int(n*0.99)]/1000:.1f}s)")
        print(f"  Max: {durations[-1]:,}ms ({durations[-1]/1000:.1f}s)")
        print()
        for threshold_s in [5, 8, 10, 15, 20, 30]:
            threshold_ms = threshold_s * 1000
            over = sum(1 for d in durations if d > threshold_ms)
            print(f"  >{threshold_s}s: {over}/{n} ({over/n*100:.2f}%)")

        # Sister session calls specifically (sister sessions use utility model)
        # These are the ones the 10/15s timeouts apply to
        print()
        print("  Note: sister session calls (plan inference, title generation)")
        print("  use a small/fast model. Main agent LLM calls use the primary model.")
        print("  The timeout values apply to sister session calls only.")

        # Check by model to separate sister session from main agent
        model_rows = conn.execute("""
            SELECT model, COUNT(*) as cnt,
                   AVG(duration_ms) as avg_ms,
                   MAX(duration_ms) as max_ms
            FROM job_telemetry_spans
            WHERE span_type = 'llm' AND duration_ms IS NOT NULL
            GROUP BY model ORDER BY cnt DESC
        """).fetchall()
        if model_rows:
            print()
            print(f"  {'Model':<30} {'Count':>6} {'Avg ms':>8} {'Max ms':>8}")
            print(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*8}")
            for r in model_rows:
                print(f"  {(r['model'] or 'unknown'):<30} {r['cnt']:>6} {r['avg_ms']:>8.0f} {r['max_ms']:>8.0f}")
    else:
        print("No LLM span data found.")

    conn.close()


if __name__ == "__main__":
    run()
