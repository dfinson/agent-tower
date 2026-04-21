"""
Entry depth evaluation — is _CONTENT_MAX=800 the right truncation per entry?

The buffer keeps 10 entries, snapshot persists 8 (proposed). Each entry's
content is truncated at 800 chars. But we don't know:

  1. How often does truncation actually fire?
  2. When it fires, how much content is lost?
  3. Does the lost content contain important signals (file paths, code)?

This experiment measures the raw content sizes BEFORE truncation would
apply, by reading directly from TranscriptUpdated event payloads.

Usage:
    python tools/content_max_eval.py
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

EXCLUDED_ROLES = frozenset({"agent_delta", "reasoning_delta", "tool_output_delta", "tool_running"})

# Regex to find file path patterns in content
FILE_PATH_RE = re.compile(r'[\w\-./]+\.\w{1,5}')


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT payload FROM events
        WHERE kind = 'TranscriptUpdated'
        ORDER BY id ASC
    """).fetchall()

    # Per-role and per-field size distributions
    # Fields: content, tool_args
    role_content_sizes: dict[str, list[int]] = defaultdict(list)
    role_args_sizes: dict[str, list[int]] = defaultdict(list)

    # How often truncation fires at various thresholds
    thresholds = [400, 600, 800, 1000, 1200, 1600, 2000, 3000]
    # content_truncated[threshold] = count of entries where content > threshold
    content_truncated: dict[int, int] = {t: 0 for t in thresholds}
    args_truncated: dict[int, int] = {t: 0 for t in thresholds}

    # When truncation fires at 800, what's in the lost tail?
    tail_has_file_path = 0  # content or args tail (past 800) contains a file path
    tail_total = 0  # entries where truncation fires at 800
    tail_sizes: list[int] = []  # size of the truncated tail

    total_entries = 0
    total_bufferable = 0  # entries that would enter the ring buffer (not excluded)

    for row in rows:
        p = json.loads(row["payload"])
        role = p.get("role", "")
        total_entries += 1

        if role in EXCLUDED_ROLES:
            continue
        total_bufferable += 1

        content = str(p.get("content", "") or "")
        tool_args = str(p.get("tool_args", "") or "")

        content_len = len(content)
        args_len = len(tool_args)

        role_content_sizes[role].append(content_len)
        if tool_args:
            role_args_sizes[role].append(args_len)

        for t in thresholds:
            if content_len > t:
                content_truncated[t] += 1
            if args_len > t:
                args_truncated[t] += 1

        # Analyze what's lost at 800
        if content_len > 800:
            tail = content[800:]
            tail_total += 1
            tail_sizes.append(len(tail))
            if FILE_PATH_RE.search(tail):
                tail_has_file_path += 1

        if args_len > 800:
            tail = tool_args[800:]
            tail_total += 1
            tail_sizes.append(len(tail))
            if FILE_PATH_RE.search(tail):
                tail_has_file_path += 1

    conn.close()

    print(f"Total TranscriptUpdated events: {total_entries}")
    print(f"Bufferable entries (not excluded roles): {total_bufferable}")
    print()

    # === Report 1: Content size distribution by role ===
    print("=" * 90)
    print("CONTENT SIZE DISTRIBUTION BY ROLE")
    print("=" * 90)
    print()
    print(f"{'Role':<20} {'Count':>7} {'P50':>6} {'P75':>6} {'P90':>6} {'P95':>6} {'P99':>6} {'Max':>7} {'>800':>5}")
    print("-" * 90)

    for role in sorted(role_content_sizes.keys()):
        sizes = sorted(role_content_sizes[role])
        n = len(sizes)
        if n == 0:
            continue
        p50 = sizes[n // 2]
        p75 = sizes[int(n * 0.75)]
        p90 = sizes[int(n * 0.90)]
        p95 = sizes[int(n * 0.95)]
        p99 = sizes[int(n * 0.99)]
        mx = sizes[-1]
        over800 = sum(1 for s in sizes if s > 800)
        pct = over800 / n * 100

        print(f"{role:<20} {n:>7,} {p50:>6,} {p75:>6,} {p90:>6,} {p95:>6,} {p99:>6,} {mx:>7,} {pct:>4.1f}%")

    print()

    # === Report 2: Tool args size distribution by role ===
    print("=" * 90)
    print("TOOL_ARGS SIZE DISTRIBUTION BY ROLE")
    print("=" * 90)
    print()
    print(f"{'Role':<20} {'Count':>7} {'P50':>6} {'P75':>6} {'P90':>6} {'P95':>6} {'P99':>6} {'Max':>7} {'>800':>5}")
    print("-" * 90)

    for role in sorted(role_args_sizes.keys()):
        sizes = sorted(role_args_sizes[role])
        n = len(sizes)
        if n == 0:
            continue
        p50 = sizes[n // 2]
        p75 = sizes[int(n * 0.75)]
        p90 = sizes[int(n * 0.90)]
        p95 = sizes[int(n * 0.95)]
        p99 = sizes[int(n * 0.99)]
        mx = sizes[-1]
        over800 = sum(1 for s in sizes if s > 800)
        pct = over800 / n * 100

        print(f"{role:<20} {n:>7,} {p50:>6,} {p75:>6,} {p90:>6,} {p95:>6,} {p99:>6,} {mx:>7,} {pct:>4.1f}%")

    print()

    # === Report 3: Truncation frequency at various thresholds ===
    print("=" * 90)
    print("TRUNCATION FREQUENCY (how often content or args exceed threshold)")
    print("=" * 90)
    print()
    print(f"{'Threshold':>9}  {'Content >':>10}  {'% of buff':>10}  {'Args >':>10}  {'% of buff':>10}  {'Either':>10}")
    print("-" * 90)

    for t in thresholds:
        c_count = content_truncated[t]
        a_count = args_truncated[t]
        c_pct = c_count / total_bufferable * 100
        a_pct = a_count / total_bufferable * 100
        # Rough "either" — upper bound
        either_pct = min(c_pct + a_pct, 100)

        print(f"{t:>9,}  {c_count:>10,}  {c_pct:>9.1f}%  {a_count:>10,}  {a_pct:>9.1f}%  {either_pct:>9.1f}%")

    print()

    # === Report 4: What's in the lost tail at 800? ===
    print("=" * 90)
    print("ANALYSIS OF TRUNCATED CONTENT (what's lost past 800 chars)")
    print("=" * 90)
    print()
    print(f"Entries where content OR args exceed 800: {tail_total}")
    if tail_total > 0:
        tail_sizes_sorted = sorted(tail_sizes)
        n = len(tail_sizes_sorted)
        print(f"Tail size (chars lost):")
        print(f"  P50: {tail_sizes_sorted[n // 2]:,}")
        print(f"  P90: {tail_sizes_sorted[int(n * 0.90)]:,}")
        print(f"  P95: {tail_sizes_sorted[int(n * 0.95)]:,}")
        print(f"  Max: {tail_sizes_sorted[-1]:,}")
        print()
        print(f"Tails containing file paths: {tail_has_file_path}/{tail_total} "
              f"({tail_has_file_path / tail_total * 100:.1f}%)")
        print()
        print("This means: when truncation fires, what percentage of the time")
        print("does it cut off content that contains a recognizable file path?")
        print("High percentage = we're losing signal. Low = we're cutting noise.")
    else:
        print("No truncation occurs at 800.")

    print()

    # === Report 5: Per-role breakdown of what exceeds 800 ===
    print("=" * 90)
    print("WHICH ROLES ARE BEING TRUNCATED? (content > 800)")
    print("=" * 90)
    print()
    for role in sorted(role_content_sizes.keys()):
        sizes = role_content_sizes[role]
        over = [s for s in sizes if s > 800]
        if not over:
            continue
        n_over = len(over)
        n_total = len(sizes)
        over_sorted = sorted(over)
        print(f"{role}: {n_over}/{n_total} entries ({n_over / n_total * 100:.1f}%) exceed 800")
        print(f"  When truncated — size P50: {over_sorted[len(over_sorted)//2]:,}, "
              f"P90: {over_sorted[int(len(over_sorted)*0.90)]:,}, "
              f"Max: {over_sorted[-1]:,}")
        print(f"  Chars lost — P50: {over_sorted[len(over_sorted)//2] - 800:,}, "
              f"P90: {over_sorted[int(len(over_sorted)*0.90)] - 800:,}")
        print()

    for role in sorted(role_args_sizes.keys()):
        sizes = role_args_sizes[role]
        over = [s for s in sizes if s > 800]
        if not over:
            continue
        n_over = len(over)
        n_total = len(sizes)
        over_sorted = sorted(over)
        print(f"{role} (tool_args): {n_over}/{n_total} entries ({n_over / n_total * 100:.1f}%) exceed 800")
        print(f"  When truncated — size P50: {over_sorted[len(over_sorted)//2]:,}, "
              f"P90: {over_sorted[int(len(over_sorted)*0.90)]:,}, "
              f"Max: {over_sorted[-1]:,}")
        print(f"  Chars lost — P50: {over_sorted[len(over_sorted)//2] - 800:,}, "
              f"P90: {over_sorted[int(len(over_sorted)*0.90)] - 800:,}")
        print()


if __name__ == "__main__":
    run()
