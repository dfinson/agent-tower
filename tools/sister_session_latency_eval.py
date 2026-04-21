"""
Sister session latency evaluation — haiku-only, filtered from main agent calls.

Questions:
  1. What's the actual haiku latency distribution?
  2. How often do 10s and 15s timeouts fire on haiku calls?
  3. What's a safe timeout that catches genuine hangs without killing slow-but-valid calls?
  4. Would retry help — are failures transient?

Usage:
    python tools/sister_session_latency_eval.py
"""

import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # === Get ALL LLM spans with durations ===
    all_llm = conn.execute("""
        SELECT name, duration_ms, started_at
        FROM job_telemetry_spans
        WHERE span_type = 'llm' AND duration_ms IS NOT NULL
        ORDER BY duration_ms ASC
    """).fetchall()

    # Separate by model
    model_durations: dict[str, list[int]] = defaultdict(list)
    for r in all_llm:
        model_durations[r["name"]].append(r["duration_ms"])

    print("=" * 80)
    print("1. LLM CALL DURATION BY MODEL")
    print("=" * 80)
    print()

    haiku_durations: list[int] = []
    non_haiku_durations: list[int] = []

    for model, durations in sorted(model_durations.items(), key=lambda x: -len(x[1])):
        durations.sort()
        n = len(durations)
        is_haiku = "haiku" in model.lower()
        tag = " ← sister session model" if is_haiku else ""

        print(f"{model}{tag}: {n} calls")
        print(f"  P50: {durations[n//2]:,}ms ({durations[n//2]/1000:.1f}s)")
        print(f"  P75: {durations[int(n*0.75)]:,}ms")
        print(f"  P90: {durations[int(n*0.90)]:,}ms")
        print(f"  P95: {durations[int(n*0.95)]:,}ms")
        print(f"  P99: {durations[int(n*0.99)]:,}ms")
        print(f"  Max: {durations[-1]:,}ms ({durations[-1]/1000:.1f}s)")
        for t in [5, 10, 15, 20, 30, 60]:
            over = sum(1 for d in durations if d > t * 1000)
            if over > 0:
                print(f"  >{t}s: {over}/{n} ({over/n*100:.2f}%)")
        print()

        if is_haiku:
            haiku_durations.extend(durations)
        else:
            non_haiku_durations.extend(durations)

    # === Haiku-specific deep dive ===
    print("=" * 80)
    print("2. HAIKU (SISTER SESSION) DEEP DIVE")
    print("=" * 80)
    print()

    if haiku_durations:
        haiku_durations.sort()
        n = len(haiku_durations)
        print(f"Total haiku calls: {n}")
        print()

        # Timeout impact analysis
        print("Timeout impact (calls that would be killed at each threshold):")
        for timeout_s in [10, 15, 20, 25, 30, 45, 60]:
            killed = sum(1 for d in haiku_durations if d > timeout_s * 1000)
            if killed > 0:
                print(f"  timeout={timeout_s}s: {killed}/{n} killed ({killed/n*100:.2f}%)")
                # Of those killed, how many are just slow vs genuine hangs?
                slow_ones = [d for d in haiku_durations if d > timeout_s * 1000]
                within_2x = sum(1 for d in slow_ones if d <= timeout_s * 2000)
                print(f"    Of those, {within_2x} finish within 2x timeout (just slow, not hung)")
                genuine_hangs = sum(1 for d in slow_ones if d > timeout_s * 3000)
                print(f"    Genuine hangs (>3x timeout): {genuine_hangs}")
        print()

        # Time-of-day pattern
        print("Slow calls (>15s) — are they clustered?")
        slow_rows = conn.execute("""
            SELECT name, duration_ms, started_at, job_id
            FROM job_telemetry_spans
            WHERE span_type = 'llm'
              AND name LIKE '%haiku%'
              AND duration_ms > 15000
            ORDER BY started_at ASC
        """).fetchall()

        if slow_rows:
            # Check if slow calls cluster in certain jobs
            job_slow_counts: dict[str, int] = defaultdict(int)
            for r in slow_rows:
                job_slow_counts[r["job_id"]] += 1

            counts = sorted(job_slow_counts.values(), reverse=True)
            print(f"  {len(slow_rows)} slow calls across {len(job_slow_counts)} jobs")
            print(f"  Calls per job: max={counts[0]}, top-3={counts[:3]}")

            # Check for bursty patterns (multiple slow calls in quick succession)
            if len(slow_rows) > 1:
                gaps = []
                for i in range(1, len(slow_rows)):
                    gap = slow_rows[i]["started_at"] - slow_rows[i-1]["started_at"]
                    gaps.append(gap)
                gaps.sort()
                ng = len(gaps)
                print(f"  Gap between consecutive slow calls:")
                print(f"    P10={gaps[int(ng*0.10)]:.0f}s, P50={gaps[ng//2]:.0f}s, "
                      f"Min={gaps[0]:.0f}s")
                burst_count = sum(1 for g in gaps if g < 30)
                print(f"    Bursts (<30s apart): {burst_count} ({burst_count/ng*100:.0f}%)")
                print(f"    → If bursty, suggests provider degradation, not individual call issues")
        print()

        # Would retry help?
        print("Retry analysis:")
        print("  If a slow call (>15s) is retried, what's the probability the retry succeeds faster?")
        print("  (Proxy: consecutive haiku calls — does the next call after a slow one tend to be fast?)")

        all_haiku_rows = conn.execute("""
            SELECT duration_ms FROM job_telemetry_spans
            WHERE span_type = 'llm'
              AND name LIKE '%haiku%'
              AND duration_ms IS NOT NULL
            ORDER BY started_at ASC
        """).fetchall()

        if len(all_haiku_rows) > 1:
            after_slow_durations = []
            for i in range(len(all_haiku_rows) - 1):
                if all_haiku_rows[i]["duration_ms"] > 15000:
                    after_slow_durations.append(all_haiku_rows[i+1]["duration_ms"])

            if after_slow_durations:
                after_slow_durations.sort()
                na = len(after_slow_durations)
                fast_after_slow = sum(1 for d in after_slow_durations if d < 10000)
                print(f"  Calls immediately after a slow (>15s) call: {na}")
                print(f"  Of those, {fast_after_slow}/{na} ({fast_after_slow/na*100:.0f}%) "
                      f"complete in <10s")
                print(f"  P50: {after_slow_durations[na//2]:,}ms")
                if fast_after_slow / na > 0.7:
                    print(f"  → Retry would help: most calls after a slow one are fast")
                else:
                    print(f"  → Retry may not help: slow calls tend to cluster")
    else:
        print("No haiku data found.")

    # === Report 3: Recommended timeout ===
    print()
    print("=" * 80)
    print("3. RECOMMENDATION")
    print("=" * 80)
    print()

    if haiku_durations:
        n = len(haiku_durations)
        # Find the timeout that kills < 1% of calls
        for t in range(10, 120, 5):
            killed = sum(1 for d in haiku_durations if d > t * 1000)
            pct = killed / n * 100
            if pct < 1.0:
                print(f"Timeout that kills <1% of calls: {t}s ({killed}/{n} = {pct:.2f}%)")
                break

        for t in range(10, 120, 5):
            killed = sum(1 for d in haiku_durations if d > t * 1000)
            pct = killed / n * 100
            if pct < 0.5:
                print(f"Timeout that kills <0.5% of calls: {t}s ({killed}/{n} = {pct:.2f}%)")
                break

        for t in range(10, 120, 5):
            killed = sum(1 for d in haiku_durations if d > t * 1000)
            pct = killed / n * 100
            if pct < 0.1:
                print(f"Timeout that kills <0.1% of calls: {t}s ({killed}/{n} = {pct:.2f}%)")
                break

    conn.close()


if __name__ == "__main__":
    run()
