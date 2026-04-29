"""
Buffer bloat evaluation — what's the actual size of entries in the ring buffer?

Now that _CONTENT_MAX is removed, entries store full content + full tool_args.
Questions:
  1. What's the actual size distribution of buffer entries (per role)?
  2. What does an 8-entry snapshot look like in bytes?
  3. How often would a snapshot exceed reasonable token budgets?
  4. Are the 68K tool_args outliers or common?

Usage:
    python tools/buffer_bloat_eval.py
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

EXCLUDED_ROLES = frozenset({"agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"})


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT payload FROM events
        WHERE kind = 'TranscriptUpdated'
        ORDER BY id ASC
    """).fetchall()

    # Simulate the ring buffer per job — no truncation, exactly as the code
    # now works after removing _CONTENT_MAX.
    job_buffers: dict[str, list[dict]] = defaultdict(list)
    BUFFER_SIZE = 10

    # Collect all snapshot sizes (at each step boundary = when buffer is read)
    # We approximate: take a snapshot every time the buffer is full
    snapshot_sizes: list[int] = []
    snapshot_token_estimates: list[int] = []

    # Per-entry sizes
    entry_sizes_by_role: dict[str, list[int]] = defaultdict(list)

    # tool_args specifically
    tool_args_sizes: list[int] = []
    tool_args_over_thresholds: dict[int, int] = {1000: 0, 5000: 0, 10000: 0, 20000: 0, 50000: 0}

    # Per-entry breakdown: content vs tool_args contribution
    content_sizes: list[int] = []
    args_in_entry_sizes: list[int] = []

    total = 0
    buffered = 0

    for row in rows:
        p = json.loads(row["payload"])
        role = p.get("role", "")
        job_id = p.get("job_id", "") or "unknown"
        total += 1

        if role in EXCLUDED_ROLES:
            continue
        buffered += 1

        # Build the entry exactly as step_tracker.py does (post-fix: no truncation)
        content = str(p.get("content", "") or "")
        entry: dict[str, str] = {
            "role": role,
            "content": content,
        }
        t_name = p.get("tool_name")
        if t_name:
            entry["tool_name"] = str(t_name)
            t_args = p.get("tool_args")
            if t_args:
                entry["tool_args"] = str(t_args)

        entry_json = json.dumps(entry, ensure_ascii=False)
        entry_size = len(entry_json)
        entry_sizes_by_role[role].append(entry_size)

        content_sizes.append(len(content))
        args_str = entry.get("tool_args", "")
        if args_str:
            args_in_entry_sizes.append(len(args_str))
            tool_args_sizes.append(len(args_str))
            for t in tool_args_over_thresholds:
                if len(args_str) > t:
                    tool_args_over_thresholds[t] += 1

        # Add to simulated buffer
        buf = job_buffers[job_id]
        buf.append(entry)
        if len(buf) > BUFFER_SIZE:
            del buf[:len(buf) - BUFFER_SIZE]

        # Take a snapshot periodically (every 10th buffered entry per job simulates step close)
        if buffered % 10 == 0 and buf:
            snapshot = buf[-8:]
            snap_json = json.dumps(snapshot, ensure_ascii=False)
            snapshot_sizes.append(len(snap_json))
            # ~4 chars per token is a rough estimate
            snapshot_token_estimates.append(len(snap_json) // 4)

    conn.close()

    print(f"Total events: {total}, Buffered: {buffered}")
    print()

    # === Report 1: Entry sizes by role ===
    print("=" * 90)
    print("ENTRY SIZE (full JSON) BY ROLE — no truncation")
    print("=" * 90)
    print()
    print(f"{'Role':<20} {'Count':>7} {'P50':>7} {'P75':>7} {'P90':>7} {'P95':>7} {'P99':>7} {'Max':>8}")
    print("-" * 90)

    for role in sorted(entry_sizes_by_role.keys()):
        sizes = sorted(entry_sizes_by_role[role])
        n = len(sizes)
        if n == 0:
            continue
        print(f"{role:<20} {n:>7,} {sizes[n//2]:>7,} {sizes[int(n*0.75)]:>7,} "
              f"{sizes[int(n*0.90)]:>7,} {sizes[int(n*0.95)]:>7,} {sizes[int(n*0.99)]:>7,} "
              f"{sizes[-1]:>8,}")
    print()

    # === Report 2: tool_args size distribution ===
    print("=" * 90)
    print("TOOL_ARGS SIZES (the bloat suspect)")
    print("=" * 90)
    print()
    if tool_args_sizes:
        tool_args_sizes.sort()
        n = len(tool_args_sizes)
        print(f"tool_args entries: {n}")
        print(f"  P50: {tool_args_sizes[n//2]:,}")
        print(f"  P75: {tool_args_sizes[int(n*0.75)]:,}")
        print(f"  P90: {tool_args_sizes[int(n*0.90)]:,}")
        print(f"  P95: {tool_args_sizes[int(n*0.95)]:,}")
        print(f"  P99: {tool_args_sizes[int(n*0.99)]:,}")
        print(f"  Max: {tool_args_sizes[-1]:,}")
        print()
        for t, count in sorted(tool_args_over_thresholds.items()):
            print(f"  >{t:,}: {count}/{n} ({count/n*100:.1f}%)")
        print()

        # What are the 68K+ entries? Show the tool names
        print("  Entries >10K chars — what tools produce these?")
    print()

    # Re-scan for the big ones
    conn2 = sqlite3.connect(str(DB_PATH))
    conn2.row_factory = sqlite3.Row
    big_rows = conn2.execute("""
        SELECT payload FROM events
        WHERE kind = 'TranscriptUpdated'
        ORDER BY id ASC
    """).fetchall()

    big_tool_counts: dict[str, list[int]] = defaultdict(list)
    for row in big_rows:
        p = json.loads(row["payload"])
        role = p.get("role", "")
        if role in EXCLUDED_ROLES:
            continue
        t_args = p.get("tool_args")
        t_name = p.get("tool_name", "unknown")
        if t_args and len(str(t_args)) > 10000:
            big_tool_counts[t_name].append(len(str(t_args)))

    for tool, sizes in sorted(big_tool_counts.items(), key=lambda x: -len(x[1])):
        sizes.sort()
        print(f"    {tool}: {len(sizes)} entries, P50={sizes[len(sizes)//2]:,}, Max={sizes[-1]:,}")
    conn2.close()
    print()

    # === Report 3: 8-entry snapshot sizes (the actual preceding_context) ===
    print("=" * 90)
    print("8-ENTRY SNAPSHOT SIZES (preceding_context after removing _CONTENT_MAX)")
    print("=" * 90)
    print()
    if snapshot_sizes:
        snapshot_sizes.sort()
        n = len(snapshot_sizes)
        print(f"Snapshots sampled: {n}")
        print(f"  P50: {snapshot_sizes[n//2]:,} chars ({snapshot_token_estimates[n//2]:,} est. tokens)")
        print(f"  P75: {snapshot_sizes[int(n*0.75)]:,} chars ({snapshot_token_estimates[int(n*0.75)]:,} est. tokens)")
        print(f"  P90: {snapshot_sizes[int(n*0.90)]:,} chars ({snapshot_token_estimates[int(n*0.90)]:,} est. tokens)")
        print(f"  P95: {snapshot_sizes[int(n*0.95)]:,} chars ({snapshot_token_estimates[int(n*0.95)]:,} est. tokens)")
        print(f"  P99: {snapshot_sizes[int(n*0.99)]:,} chars ({snapshot_token_estimates[int(n*0.99)]:,} est. tokens)")
        print(f"  Max: {snapshot_sizes[-1]:,} chars ({snapshot_token_estimates[-1]:,} est. tokens)")
        print()

        # Compare to old regime (800 cap)
        print("  For comparison, old regime (800 cap per entry):")
        old_max = 8 * 800 * 2  # 8 entries × 800 chars × ~2 fields
        print(f"    Theoretical max: ~{old_max:,} chars")
        print(f"    New P99/Old max ratio: {snapshot_sizes[int(n*0.99)] / old_max:.1f}x")
        print()

        # Token budget analysis
        for budget in [2000, 4000, 8000, 16000]:
            over = sum(1 for s in snapshot_token_estimates if s > budget)
            print(f"  Snapshots exceeding {budget:,} token budget: {over}/{n} ({over/n*100:.1f}%)")
    print()

    # === Report 4: What fraction of snapshot size comes from tool_args? ===
    print("=" * 90)
    print("CONTENT vs TOOL_ARGS contribution to entry size")
    print("=" * 90)
    print()
    if content_sizes and args_in_entry_sizes:
        content_sizes.sort()
        args_in_entry_sizes.sort()
        nc = len(content_sizes)
        na = len(args_in_entry_sizes)
        print(f"Content (all entries): P50={content_sizes[nc//2]:,}, P90={content_sizes[int(nc*0.90)]:,}, "
              f"P99={content_sizes[int(nc*0.99)]:,}, Max={content_sizes[-1]:,}")
        print(f"Tool_args (entries that have them): P50={args_in_entry_sizes[na//2]:,}, "
              f"P90={args_in_entry_sizes[int(na*0.90)]:,}, "
              f"P99={args_in_entry_sizes[int(na*0.99)]:,}, Max={args_in_entry_sizes[-1]:,}")
        print()
        print("tool_args dominates entry size. Content is usually small (tool_call content = tool name).")
        print("Question: should tool_args be in the buffer at all, or stored separately?")


if __name__ == "__main__":
    run()
