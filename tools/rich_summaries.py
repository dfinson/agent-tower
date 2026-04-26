"""Extract 20 file_write spans with 5-turn context + job description, then
summarize each via gpt-4o-mini on GitHub Models.

Usage:
    GH_TOKEN=$(gh auth token) uv run python tools/rich_summaries.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

DB_PATH = Path.home() / ".codeplane" / "data.db"
GH_MODELS_URL = "https://models.inference.ai.azure.com/chat/completions"
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """\
You explain why a code change was made. Write in abstract third person — no "I", \
no "the agent", no "this edit", no "this change".

Output exactly two lines of plain text (no markdown, no headers, no bullets):
LINE 1: Title — ≤10 words. Name the file and what changed. No filler words.
LINE 2: WHY — 1-2 sentences. Only explain what isn't obvious from the diff. \
Reference the specific prior finding, bug, or upstream change that caused this. \
Cite concrete file paths, function names, finding IDs, or todo IDs from the context. \
Never restate what the diff already shows. Never say "aligns with", "ensures consistency", \
"improves maintainability", or similar filler.

Example output:
Strip whitespace before validation in models.py TicketCreate
service.py was stripping after Pydantic's min_length=1 check, so "   " (3 spaces) passed validation then became empty. Moving strip into a mode='before' field_validator on TicketCreate fixes this without touching service.py.

Never fabricate references. Only cite what appears in the provided context.
"""


def get_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: No GitHub token. Run: GH_TOKEN=$(gh auth token) uv run python tools/rich_summaries.py")
        sys.exit(1)


def extract_examples(conn: sqlite3.Connection, n: int = 20) -> list[dict]:
    conn.row_factory = sqlite3.Row

    spans = conn.execute("""
        SELECT s.id, s.job_id, s.name AS tool_name, s.tool_args_json AS tool_args, s.turn_id,
               j.description AS job_description, j.title AS job_name, j.prompt AS job_prompt
        FROM job_telemetry_spans s
        JOIN jobs j ON j.id = s.job_id
        WHERE s.name IN ('edit', 'Edit', 'create', 'write_file')
          AND s.tool_args_json IS NOT NULL
          AND s.turn_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM events e WHERE e.job_id = s.job_id AND e.kind = 'TranscriptUpdated')
        ORDER BY RANDOM()
        LIMIT ?
    """, (n,)).fetchall()

    examples = []
    for span in spans:
        job_id = span["job_id"]
        turn_id = span["turn_id"]

        try:
            args = json.loads(span["tool_args"])
        except (json.JSONDecodeError, TypeError):
            args = {}

        target_file = args.get("path") or args.get("file_path") or args.get("file") or "(unknown)"

        old_str = args.get("old_str") or args.get("old_string") or args.get("oldString") or ""
        new_str = args.get("new_str") or args.get("new_string") or args.get("newString") or ""
        file_text = args.get("file_text") or ""

        if old_str and new_str:
            diff = f"REPLACE in {target_file}:\n--- old ---\n{old_str[:600]}\n--- new ---\n{new_str[:600]}"
        elif file_text:
            diff = f"CREATE {target_file}:\n{file_text[:600]}"
        elif new_str:
            diff = f"INSERT in {target_file}:\n{new_str[:600]}"
        else:
            diff = f"{span['tool_name']}({target_file})"

        raw_events = conn.execute("""
            SELECT e.id, e.payload FROM events e
            WHERE e.job_id = ? AND e.kind = 'TranscriptUpdated'
            ORDER BY e.id
        """, (job_id,)).fetchall()

        parsed = []
        for rev in raw_events:
            try:
                p = json.loads(rev["payload"])
            except (json.JSONDecodeError, TypeError):
                continue  # malformed event payload — skip
            parsed.append({
                "id": rev["id"],
                "role": p.get("role", ""),
                "content": p.get("content", ""),
                "turn_id": p.get("turn_id"),
                "tool_name": p.get("tool_name", ""),
                "tool_args": p.get("tool_args", ""),
                "tool_intent": p.get("tool_intent", ""),
            })

        target_idx = None
        for idx, ev in enumerate(parsed):
            if ev["turn_id"] == turn_id:
                target_idx = idx
                break
        if target_idx is None:
            target_idx = len(parsed) - 1

        seen_turns: set[str] = set()
        for idx in range(target_idx - 1, -1, -1):
            ev_turn = parsed[idx]["turn_id"]
            if ev_turn and ev_turn not in seen_turns and ev_turn != turn_id:
                seen_turns.add(ev_turn)
                if len(seen_turns) >= 5:
                    break

        context_lines = []
        for idx in range(max(0, target_idx - 100), target_idx):
            ev = parsed[idx]
            if ev["turn_id"] not in seen_turns:
                continue
            role = ev["role"]
            text = ""

            if role == "reasoning":
                if ev["content"]:
                    text = f"[THINKING] {ev['content'][:350]}"
            elif role == "agent":
                if ev["content"]:
                    text = f"[AGENT] {ev['content'][:500]}"
            elif role == "tool_call":
                tn = ev["tool_name"] or ev["content"]
                ta_raw = ev["tool_args"]
                try:
                    ta = json.loads(ta_raw) if isinstance(ta_raw, str) else (ta_raw or {})
                except (json.JSONDecodeError, TypeError):
                    ta = {}
                if isinstance(ta, dict):
                    compact = {}
                    for k, v in ta.items():
                        compact[k] = f"[{len(v)} chars]" if isinstance(v, str) and len(v) > 150 else v
                    text = f"[TOOL] {tn}({json.dumps(compact, ensure_ascii=False)[:300]})"
                else:
                    text = f"[TOOL] {tn}(...)"
                if ev["tool_intent"]:
                    text += f" — intent: {ev['tool_intent'][:100]}"
            elif role == "user":
                if ev["content"]:
                    text = f"[USER] {ev['content'][:250]}"

            if text:
                context_lines.append(text)

        job_desc = span["job_description"] or span["job_prompt"] or "(no description)"
        examples.append({
            "job_name": span["job_name"] or "(unnamed)",
            "job_id": job_id[:12],
            "job_description": job_desc[:400],
            "target_file": target_file,
            "tool_name": span["tool_name"],
            "diff": diff,
            "context": context_lines,
        })

    return examples


def summarize(client: httpx.Client, token: str, example: dict) -> str:
    context_block = "\n".join(example["context"]) if example["context"] else "(no preceding context)"
    user_msg = f"""## Job Description
{example['job_description']}

## Action
{example['tool_name']}({example['target_file']})

## Diff
{example['diff']}

## Preceding Context ({len(example['context'])} events)
{context_block}
"""

    resp = client.post(
        GH_MODELS_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 150,
            "temperature": 0.2,
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def main():
    token = get_token()
    conn = sqlite3.connect(str(DB_PATH))

    print("Extracting 20 examples from DB...")
    examples = extract_examples(conn, 20)
    conn.close()
    print(f"Got {len(examples)} examples. Summarizing via {MODEL} on GitHub Models...\n")

    client = httpx.Client()
    for i, ex in enumerate(examples, 1):
        print("=" * 80)
        print(f"EXAMPLE {i} | job: {ex['job_name']} | file: {ex['target_file']}")
        print(f"JOB DESC: {ex['job_description'][:200]}")
        print()
        print("--- DIFF ---")
        print(ex["diff"])
        print()

        try:
            summary = summarize(client, token, ex)
            print("--- SUMMARY (gpt-4o-mini) ---")
            print(summary)
        except Exception as e:
            print(f"--- SUMMARY FAILED: {e} ---")

        print()
        print(f"--- RAW INPUT ({len(ex['context'])} context events) ---")
        for line in ex["context"]:
            print(f"  {line}")
        print()

        if i < len(examples):
            time.sleep(4)

    client.close()
    print(f"\nDone. {len(examples)} examples processed.")


if __name__ == "__main__":
    main()
