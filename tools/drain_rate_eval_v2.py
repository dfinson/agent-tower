"""
Drain rate evaluation v2 — parallel processing model.

The v1 simulation was wrong: it modeled sequential span processing.
In reality, asyncio.gather processes a batch concurrently.
This version models parallel batches correctly.

Usage:
    python tools/drain_rate_eval_v2.py
"""

import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    spans = conn.execute("""
        SELECT job_id, started_at, duration_ms
        FROM job_telemetry_spans
        WHERE span_type = 'tool'
          AND tool_category = 'file_write'
          AND started_at IS NOT NULL
        ORDER BY started_at ASC
    """).fetchall()

    if not spans:
        print("No write-tool spans found.")
        conn.close()
        return

    print(f"Total mutative tool spans: {len(spans)}")

    # Arrival rate context
    job_spans: dict[str, list[float]] = defaultdict(list)
    for s in spans:
        job_spans[s["job_id"]].append(s["started_at"])

    inter_arrival: list[float] = []
    for jid, times in job_spans.items():
        times.sort()
        for i in range(1, len(times)):
            gap = times[i] - times[i - 1]
            if gap > 0:
                inter_arrival.append(gap)

    inter_arrival.sort()
    n_ia = len(inter_arrival)
    print(f"Inter-arrival P50={inter_arrival[n_ia//2]:.1f}s, P25={inter_arrival[int(n_ia*0.25)]:.1f}s")
    print()

    # Haiku processing time (per-call, but batch runs in parallel)
    haiku_rows = conn.execute("""
        SELECT duration_ms FROM job_telemetry_spans
        WHERE span_type = 'llm' AND name LIKE '%haiku%' AND duration_ms IS NOT NULL
        ORDER BY duration_ms ASC
    """).fetchall()
    haiku_durations = [r["duration_ms"] for r in haiku_rows]
    n_h = len(haiku_durations)
    # A parallel batch takes MAX(individual durations), not SUM
    # P90 single call = ~14s, P95 = ~31s
    p50_call = haiku_durations[n_h // 2] / 1000
    p90_call = haiku_durations[int(n_h * 0.90)] / 1000
    p95_call = haiku_durations[int(n_h * 0.95)] / 1000
    print(f"Haiku call time: P50={p50_call:.1f}s, P90={p90_call:.1f}s, P95={p95_call:.1f}s")
    print(f"A parallel batch of N takes time ≈ max(N calls), not sum.")
    print()

    # Build global arrival timeline
    all_arrivals = sorted(s["started_at"] for s in spans)
    t0 = all_arrivals[0]
    arrivals = [t - t0 for t in all_arrivals]
    total_time = arrivals[-1]

    # For parallel batch: batch processing time = max of N independent haiku calls
    # Expected max of N iid samples from the haiku distribution
    # Approximate: for batch of N, processing time ≈ P(1-1/N) quantile
    def batch_time(batch_size: int) -> float:
        """Expected time for a parallel batch = max of batch_size iid haiku calls."""
        if batch_size <= 0:
            return 0
        quantile = 1 - 1 / max(batch_size, 2)
        idx = min(int(n_h * quantile), n_h - 1)
        return haiku_durations[idx] / 1000

    combos = [
        (5, 3.0),
        (5, 5.0),
        (10, 3.0),
        (10, 5.0),
        (10, 10.0),
        (20, 5.0),
        (20, 10.0),
        (30, 10.0),
    ]

    print("=" * 95)
    print("PARALLEL BATCH SIMULATION")
    print("=" * 95)
    print()
    print(f"{'Batch':>6} {'Interval':>9} {'Batch T':>8} {'MaxQ':>6} {'AvgQ':>6} "
          f"{'Drains':>7} {'Max wait':>9} {'Avg wait':>9} {'P95 wait':>9}")
    print("-" * 95)

    for batch_size, interval in combos:
        bt = batch_time(batch_size)

        queue: list[float] = []
        queue_depths: list[int] = []
        wait_times: list[float] = []
        drain_count = 0
        arrival_idx = 0
        t = 0.0

        while t < total_time + interval * 2:
            # Add arrivals up to time t
            while arrival_idx < len(arrivals) and arrivals[arrival_idx] <= t:
                queue.append(arrivals[arrival_idx])
                arrival_idx += 1

            queue_depths.append(len(queue))

            if queue:
                to_process = min(batch_size, len(queue))
                processed = queue[:to_process]
                queue = queue[to_process:]
                for arr in processed:
                    wait_times.append(t - arr)
                drain_count += 1
                # Parallel batch: wall-clock time = max of N calls
                t += bt
            t += interval

        # Flush remaining
        while queue:
            to_process = min(batch_size, len(queue))
            processed = queue[:to_process]
            queue = queue[to_process:]
            for arr in processed:
                wait_times.append(t - arr)
            drain_count += 1
            t += bt + interval

        max_q = max(queue_depths) if queue_depths else 0
        avg_q = sum(queue_depths) / len(queue_depths) if queue_depths else 0
        max_wait = max(wait_times) if wait_times else 0
        avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0
        wait_times.sort()
        p95_wait = wait_times[int(len(wait_times) * 0.95)] if wait_times else 0

        print(f"{batch_size:>6} {interval:>8.0f}s {bt:>7.1f}s {max_q:>6} {avg_q:>6.1f} "
              f"{drain_count:>7} {max_wait:>8.0f}s {avg_wait:>8.0f}s {p95_wait:>8.0f}s")

    print()
    print("Batch T = wall-clock time for one parallel batch (expected max of N haiku calls)")
    print()

    # Current settings analysis
    current_bt = batch_time(20)
    print(f"Current settings: batch=20, interval=10s")
    print(f"  Batch processing time: {current_bt:.1f}s")
    print(f"  Cycle time: {current_bt + 10:.1f}s")
    print(f"  Throughput: {20 / (current_bt + 10):.1f} spans/cycle = "
          f"{20 / (current_bt + 10) * 60:.0f} spans/min")
    print(f"  Arrival rate: 4.8 spans/min → headroom: "
          f"{20 / (current_bt + 10) * 60 / 4.8:.1f}x")

    conn.close()


if __name__ == "__main__":
    run()
