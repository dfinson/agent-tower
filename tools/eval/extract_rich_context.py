"""Extract 20 file_write spans with 5-turn preceding context + job description.

Outputs structured blocks that can be fed to an LLM for rich summarization.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"

def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get file_write spans that have a matching job with both spans and events
    spans = conn.execute("""
        SELECT s.id, s.job_id, s.tool_name, s.tool_args, s.turn_id,
               j.description as job_description, j.name as job_name
        FROM job_telemetry_spans s
        JOIN jobs j ON j.id = s.job_id
        WHERE s.tool_name IN ('edit', 'Edit', 'create', 'write_file')
          AND s.tool_args IS NOT NULL
          AND s.turn_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM events e WHERE e.job_id = s.job_id)
        ORDER BY RANDOM()
        LIMIT 20
    """).fetchall()

    print(f"Extracted {len(spans)} spans\n")

    for i, span in enumerate(spans, 1):
        job_id = span["job_id"]
        turn_id = span["turn_id"]
        tool_name = span["tool_name"]
        tool_args_raw = span["tool_args"]
        job_desc = span["job_description"] or "(no description)"
        job_name = span["job_name"] or "(unnamed)"

        # Parse tool args
        try:
            args = json.loads(tool_args_raw)
        except (json.JSONDecodeError, TypeError):
            args = {"raw": str(tool_args_raw)[:500]}

        # Get the target file from args
        target_file = (
            args.get("path")
            or args.get("file_path")
            or args.get("file")
            or "(unknown)"
        )

        # Build a compact diff representation
        old_str = args.get("old_str") or args.get("old_string") or args.get("oldString") or ""
        new_str = args.get("new_str") or args.get("new_string") or args.get("newString") or ""
        file_text = args.get("file_text") or ""

        if old_str and new_str:
            diff_repr = f"REPLACE in {target_file}:\n--- old ---\n{old_str[:800]}\n--- new ---\n{new_str[:800]}"
        elif file_text:
            diff_repr = f"CREATE {target_file}:\n{file_text[:800]}"
        elif new_str:
            diff_repr = f"INSERT in {target_file}:\n{new_str[:800]}"
        else:
            diff_repr = f"{tool_name}({target_file})"

        # Get events for this job, ordered by id
        events = conn.execute("""
            SELECT id, role, content, turn_id
            FROM events
            WHERE job_id = ?
            ORDER BY id
        """, (job_id,)).fetchall()

        # Find the index of the event matching this turn_id
        target_idx = None
        for idx, ev in enumerate(events):
            if ev["turn_id"] == turn_id:
                target_idx = idx
                break

        if target_idx is None:
            # Find closest match by looking for recent events before this span
            target_idx = len(events) - 1

        # Collect preceding 5 turns (turn = unique turn_id)
        preceding_turn_ids = []
        seen_turns = set()
        for idx in range(target_idx - 1, -1, -1):
            ev_turn = events[idx]["turn_id"]
            if ev_turn and ev_turn not in seen_turns and ev_turn != turn_id:
                seen_turns.add(ev_turn)
                preceding_turn_ids.append(ev_turn)
                if len(preceding_turn_ids) >= 5:
                    break

        preceding_turn_ids.reverse()

        # Collect all events from those turns
        context_events = []
        for idx in range(max(0, target_idx - 60), target_idx):
            ev = events[idx]
            ev_turn = ev["turn_id"]
            if ev_turn in seen_turns:
                role = ev["role"]
                content_raw = ev["content"] or ""

                try:
                    payload = json.loads(content_raw)
                except (json.JSONDecodeError, TypeError):
                    payload = {}

                if role == "tool_result":
                    # Skip tool results (they're huge)
                    continue

                text = ""
                if role == "reasoning":
                    thinking = payload.get("thinking", "")
                    if thinking:
                        text = f"[THINKING] {thinking[:400]}"
                elif role == "agent":
                    agent_text = payload.get("text", "")
                    if agent_text:
                        text = f"[AGENT] {agent_text[:600]}"
                elif role == "tool_call":
                    tn = payload.get("tool_name", "")
                    ta = payload.get("tool_args", {})
                    # Compact tool call - just name and key args
                    if isinstance(ta, dict):
                        # Remove massive string args for readability
                        compact_args = {}
                        for k, v in ta.items():
                            if isinstance(v, str) and len(v) > 200:
                                compact_args[k] = f"[{len(v)} chars]"
                            else:
                                compact_args[k] = v
                        text = f"[TOOL] {tn}({json.dumps(compact_args, ensure_ascii=False)[:300]})"
                    else:
                        text = f"[TOOL] {tn}(...)"
                elif role == "user":
                    user_text = payload.get("text", "")
                    if user_text:
                        text = f"[USER] {user_text[:300]}"

                if text:
                    context_events.append(text)

        # Output
        print("=" * 80)
        print(f"EXAMPLE {i}")
        print(f"JOB: {job_name} (id: {job_id[:12]}...)")
        print(f"JOB DESCRIPTION: {job_desc[:500]}")
        print(f"TARGET FILE: {target_file}")
        print(f"TOOL: {tool_name}")
        print()
        print("--- DIFF ---")
        print(diff_repr)
        print()
        print(f"--- PRECEDING CONTEXT ({len(context_events)} events from {len(preceding_turn_ids)} turns) ---")
        for ev in context_events:
            print(f"  {ev}")
        print()

    conn.close()
    print(f"\nTotal: {len(spans)} examples extracted")


if __name__ == "__main__":
    main()
