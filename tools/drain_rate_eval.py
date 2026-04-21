"""
Drain rate & batch size evaluation — find the data-driven sweet spot.

Questions:
  1. What's the arrival rate of mutative tool spans per job? Per minute?
  2. How many spans queue up between drain cycles?
  3. What batch size clears the backlog without hammering the API?
  4. What drain interval keeps queue depth bounded?

We simulate the drain loop against production data:
  - For each job, measure inter-span arrival times
  - For various (batch_size, interval) combos, simulate queue depth over time
  - Find the combo that keeps max queue depth < 5 (near-real-time) with minimum API calls

Usage:
    python tools/drain_rate_eval.py
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get mutative tool spans (the ones motivation_service processes)
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
    print()

    # === Report 1: Arrival rate per job ===
    print("=" * 80)
    print("1. SPAN ARRIVAL RATE PER JOB")
    print("=" * 80)
    print()

    job_spans: dict[str, list[float]] = defaultdict(list)
    for s in spans:
        job_spans[s["job_id"]].append(s["started_at"])

    inter_arrival_times: list[float] = []  # seconds between consecutive spans per job
    spans_per_job: list[int] = []
    job_durations: list[float] = []  # total job span duration in seconds

    for jid, times in job_spans.items():
        spans_per_job.append(len(times))
        if len(times) > 1:
            sorted_times = sorted(times)
            duration = sorted_times[-1] - sorted_times[0]
            if duration > 0:
                job_durations.append(duration)
            for i in range(1, len(sorted_times)):
                gap = sorted_times[i] - sorted_times[i-1]
                if gap > 0:
                    inter_arrival_times.append(gap)

    spans_per_job.sort()
    n = len(spans_per_job)
    print(f"Jobs with mutative spans: {n}")
    print(f"Spans per job: P50={spans_per_job[n//2]}, P75={spans_per_job[int(n*0.75)]}, "
          f"P90={spans_per_job[int(n*0.90)]}, P95={spans_per_job[int(n*0.95)]}, Max={spans_per_job[-1]}")
    print()

    if inter_arrival_times:
        inter_arrival_times.sort()
        n_ia = len(inter_arrival_times)
        print(f"Inter-arrival time (seconds between consecutive mutative spans within a job):")
        print(f"  P10: {inter_arrival_times[int(n_ia*0.10)]:.1f}s")
        print(f"  P25: {inter_arrival_times[int(n_ia*0.25)]:.1f}s")
        print(f"  P50: {inter_arrival_times[n_ia//2]:.1f}s")
        print(f"  P75: {inter_arrival_times[int(n_ia*0.75)]:.1f}s")
        print(f"  P90: {inter_arrival_times[int(n_ia*0.90)]:.1f}s")
        print(f"  P95: {inter_arrival_times[int(n_ia*0.95)]:.1f}s")
        print()
        # Spans per minute (within active jobs)
        if job_durations:
            job_durations.sort()
            nd = len(job_durations)
            total_spans = sum(len(t) for t in job_spans.values() if len(t) > 1)
            total_duration = sum(job_durations)
            avg_rate = total_spans / (total_duration / 60) if total_duration > 0 else 0
            print(f"Aggregate arrival rate across all jobs: {avg_rate:.1f} spans/minute")
            print(f"  (over {total_duration/60:.0f} minutes of active job time)")
    print()

    # === Report 2: LLM processing time for motivation calls ===
    print("=" * 80)
    print("2. SISTER SESSION CALL DURATION (motivation processing time)")
    print("=" * 80)
    print()

    # Sister session calls are haiku — get haiku-specific durations
    llm_rows = conn.execute("""
        SELECT duration_ms FROM job_telemetry_spans
        WHERE span_type = 'llm'
          AND name LIKE '%haiku%'
          AND duration_ms IS NOT NULL
        ORDER BY duration_ms ASC
    """).fetchall()

    haiku_durations = [r["duration_ms"] for r in llm_rows]
    if haiku_durations:
        n_h = len(haiku_durations)
        print(f"Haiku LLM call durations: {n_h}")
        print(f"  P50: {haiku_durations[n_h//2]:,}ms ({haiku_durations[n_h//2]/1000:.1f}s)")
        print(f"  P75: {haiku_durations[int(n_h*0.75)]:,}ms")
        print(f"  P90: {haiku_durations[int(n_h*0.90)]:,}ms")
        print(f"  P95: {haiku_durations[int(n_h*0.95)]:,}ms")
        print(f"  P99: {haiku_durations[int(n_h*0.99)]:,}ms")
        print(f"  Max: {haiku_durations[-1]:,}ms ({haiku_durations[-1]/1000:.1f}s)")
        avg_haiku_ms = sum(haiku_durations) / n_h
        print(f"  Mean: {avg_haiku_ms:,.0f}ms ({avg_haiku_ms/1000:.1f}s)")
    else:
        avg_haiku_ms = 7300  # fallback from earlier measurement
        print(f"No haiku-specific data. Using earlier measurement: avg={avg_haiku_ms}ms")
    print()

    # === Report 3: Queue depth simulation ===
    print("=" * 80)
    print("3. QUEUE DEPTH SIMULATION — (batch_size, interval) combos")
    print("=" * 80)
    print()
    print("Simulating: spans arrive at observed rate, drain loop processes batches.")
    print("Each span takes ~avg_haiku_ms to process (sequential within batch).")
    print()

    # Build a global timeline of span arrivals (across all jobs)
    all_arrivals: list[float] = []
    for s in spans:
        all_arrivals.append(s["started_at"])
    all_arrivals.sort()

    if len(all_arrivals) < 10:
        print("Not enough data for simulation.")
        conn.close()
        return

    # Normalize to start at 0
    t0 = all_arrivals[0]
    arrivals = [t - t0 for t in all_arrivals]
    total_time = arrivals[-1]

    process_time_s = avg_haiku_ms / 1000  # time to process one span

    combos = [
        (5, 5.0),
        (10, 5.0),
        (10, 10.0),
        (20, 5.0),
        (20, 10.0),
        (20, 15.0),
        (30, 10.0),
        (30, 15.0),
        (50, 10.0),
    ]

    print(f"{'Batch':>6} {'Interval':>9} {'MaxQ':>6} {'AvgQ':>6} {'Drains':>7} {'LLM calls':>10} "
          f"{'Max wait':>9} {'Avg wait':>9}")
    print("-" * 80)

    for batch_size, interval in combos:
        # Simulate
        queue: list[float] = []  # arrival times of queued items
        queue_depths: list[int] = []
        wait_times: list[float] = []  # time from arrival to processing
        total_llm_calls = 0
        drain_count = 0

        arrival_idx = 0
        t = 0.0

        while t < total_time + interval:
            # Add all arrivals up to time t
            while arrival_idx < len(arrivals) and arrivals[arrival_idx] <= t:
                queue.append(arrivals[arrival_idx])
                arrival_idx += 1

            queue_depths.append(len(queue))

            # Drain up to batch_size
            if queue:
                to_process = min(batch_size, len(queue))
                processed_arrivals = queue[:to_process]
                queue = queue[to_process:]

                for arr_time in processed_arrivals:
                    wait_times.append(t - arr_time)

                total_llm_calls += to_process
                drain_count += 1

                # Processing takes time (sequential)
                t += to_process * process_time_s

            t += interval

        # Process any remaining
        while queue:
            to_process = min(batch_size, len(queue))
            processed_arrivals = queue[:to_process]
            queue = queue[to_process:]
            for arr_time in processed_arrivals:
                wait_times.append(t - arr_time)
            total_llm_calls += to_process
            drain_count += 1
            t += to_process * process_time_s + interval

        max_q = max(queue_depths) if queue_depths else 0
        avg_q = sum(queue_depths) / len(queue_depths) if queue_depths else 0
        max_wait = max(wait_times) if wait_times else 0
        avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0

        print(f"{batch_size:>6} {interval:>8.0f}s {max_q:>6} {avg_q:>6.1f} {drain_count:>7,} "
              f"{total_llm_calls:>10,} {max_wait:>8.0f}s {avg_wait:>8.0f}s")

    print()
    print("MaxQ = peak queue depth. Want < 10 for near-real-time.")
    print("LLM calls = total API calls to process all spans. Want minimal.")
    print("Max wait = longest any span waited before processing.")
    print("Avg wait = mean latency from span arrival to processing.")

    # === Report 4: Concurrent jobs ===
    print()
    print("=" * 80)
    print("4. CONCURRENT JOBS (affects effective arrival rate)")
    print("=" * 80)
    print()

    job_rows = conn.execute("""
        SELECT id, started_at, completed_at FROM jobs
        WHERE started_at IS NOT NULL
        ORDER BY started_at ASC
    """).fetchall()

    if job_rows:
        # Count max overlapping jobs
        events_list: list[tuple[str, str]] = []
        for j in job_rows:
            if j["started_at"]:
                events_list.append((j["started_at"], "start"))
            if j["completed_at"]:
                events_list.append((j["completed_at"], "end"))
        events_list.sort()

        concurrent = 0
        max_concurrent = 0
        for _, kind in events_list:
            if kind == "start":
                concurrent += 1
            else:
                concurrent -= 1
            max_concurrent = max(max_concurrent, concurrent)

        print(f"Max concurrent jobs observed: {max_concurrent}")
        print(f"Total jobs: {len(job_rows)}")
        if max_concurrent > 1:
            print(f"With {max_concurrent} concurrent jobs, effective arrival rate multiplies.")
            print(f"Batch size should handle {max_concurrent}x the single-job rate.")

    conn.close()


if __name__ == "__main__":
    run()
