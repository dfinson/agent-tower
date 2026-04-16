"""
Extract 20 file_write spans with preceding 5-turn context for summarization.

For each write:
- The action: tool name, target file, tool_args (truncated)
- Preceding 5 turns: thinking blocks, text blocks, tool name+args (no tool results)
"""
import json
import sqlite3
import textwrap
from pathlib import Path

DB_PATH = Path.home() / ".codeplane" / "data.db"
LOOKBACK_TURNS = 5
MAX_CONTENT_LEN = 600  # truncate long thinking/text blocks


def truncate(s: str, limit: int = MAX_CONTENT_LEN) -> str:
    if not s or len(s) <= limit:
        return s or ""
    return s[:limit] + f"... [{len(s) - limit} chars truncated]"


def run():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get file_write spans with turn_id, spread across different jobs
    writes = conn.execute("""
        SELECT s.id, s.job_id, s.name, s.turn_id, s.tool_target, s.tool_args_json
        FROM job_telemetry_spans s
        WHERE s.turn_id IS NOT NULL
          AND s.span_type = 'tool'
          AND s.tool_category = 'file_write'
          AND s.tool_target IS NOT NULL AND s.tool_target != ''
        ORDER BY RANDOM()
        LIMIT 60
    """).fetchall()

    # Pick up to 20, preferring diverse jobs
    seen_jobs: dict[str, int] = {}
    selected = []
    for wr in writes:
        jid = wr["job_id"]
        if seen_jobs.get(jid, 0) >= 3:  # max 3 per job
            continue
        seen_jobs[jid] = seen_jobs.get(jid, 0) + 1
        selected.append(wr)
        if len(selected) >= 20:
            break

    examples = []
    for i, wr in enumerate(selected):
        # Get the first event ID for this write's turn
        first_eid = conn.execute("""
            SELECT MIN(id) FROM events
            WHERE job_id = ? AND kind = 'TranscriptUpdated'
              AND json_extract(payload, '$.turn_id') = ?
        """, (wr["job_id"], wr["turn_id"])).fetchone()[0]
        if not first_eid:
            continue

        # Get preceding events (before this turn), newest first
        preceding = conn.execute("""
            SELECT
                json_extract(payload, '$.turn_id') AS turn_id,
                json_extract(payload, '$.role') AS role,
                json_extract(payload, '$.content') AS content,
                json_extract(payload, '$.tool_name') AS tool_name,
                json_extract(payload, '$.tool_args') AS tool_args,
                json_extract(payload, '$.tool_result') AS tool_result
            FROM events
            WHERE job_id = ?
              AND kind = 'TranscriptUpdated'
              AND id < ?
            ORDER BY id DESC
            LIMIT 500
        """, (wr["job_id"], first_eid)).fetchall()

        # Build distinct turn list (newest first), take LOOKBACK_TURNS
        seen_turns = []
        seen_set = set()
        for ev in preceding:
            tid = ev["turn_id"]
            if tid and tid not in seen_set:
                seen_set.add(tid)
                seen_turns.append(tid)
        target_turns = set(seen_turns[:LOOKBACK_TURNS])

        # Collect context from those turns (in chronological order)
        context_events = []
        for ev in reversed(preceding):
            tid = ev["turn_id"]
            if tid not in target_turns:
                continue
            role = ev["role"]

            # Skip tool results (bulk data)
            if ev["tool_result"]:
                continue

            entry = {}
            if role in ("reasoning", "agent") and ev["content"]:
                entry = {"role": role, "content": truncate(ev["content"])}
            elif ev["tool_name"]:
                # Tool call: name + args (no result)
                args_str = ""
                if ev["tool_args"]:
                    try:
                        args = json.loads(ev["tool_args"])
                        # For file reads, just show path, not content
                        clean = {}
                        for k, v in args.items():
                            if k in ("fileContents", "content", "file_text", "newString", "oldString"):
                                clean[k] = f"[{len(str(v))} chars]"
                            else:
                                clean[k] = v
                        args_str = json.dumps(clean, default=str)
                    except Exception:
                        args_str = truncate(ev["tool_args"], 200)
                entry = {"role": "tool_call", "tool": ev["tool_name"], "args": args_str}

            if entry:
                context_events.append(entry)

        # Build the write action description
        target = wr["tool_target"]
        args_preview = ""
        if wr["tool_args_json"]:
            try:
                args = json.loads(wr["tool_args_json"])
                clean = {}
                for k, v in args.items():
                    if k in ("fileContents", "content", "file_text", "newString", "oldString"):
                        clean[k] = f"[{len(str(v))} chars]"
                    else:
                        clean[k] = v
                args_preview = json.dumps(clean, default=str)
            except Exception:
                args_preview = truncate(wr["tool_args_json"], 200)

        examples.append({
            "index": i + 1,
            "job_id": wr["job_id"][:8],
            "action": f"{wr['name']}({target})",
            "args_preview": args_preview,
            "preceding_context": context_events,
        })

    conn.close()

    # Output as structured text for summarization
    for ex in examples:
        print(f"{'=' * 80}")
        print(f"EXAMPLE {ex['index']} (job {ex['job_id']})")
        print(f"ACTION: {ex['action']}")
        print(f"ARGS: {ex['args_preview']}")
        print(f"\nPRECEDING CONTEXT ({len(ex['preceding_context'])} events from last {LOOKBACK_TURNS} turns):")
        for ev in ex['preceding_context']:
            if ev["role"] in ("reasoning", "agent"):
                print(f"  [{ev['role'].upper()}] {ev['content']}")
            elif ev["role"] == "tool_call":
                print(f"  [TOOL_CALL] {ev['tool']}({ev['args']})")
        print()

    print(f"{'=' * 80}")
    print(f"Total examples extracted: {len(examples)}")


if __name__ == "__main__":
    run()
