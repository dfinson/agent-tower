"""Trail LLM prompt templates — isolated for independent iteration."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

log = structlog.get_logger()

if TYPE_CHECKING:
    from backend.models.db import TrailNodeRow

ENRICH_SYSTEM_PROMPT = (
    "You annotate agent trail nodes with intent, rationale, outcome, and tags. "
    "You also detect semantic patterns (plan, insight, decide, backtrack, verify) "
    "from the agent's transcript. Be concrete: cite file names, function names, "
    "line numbers from the context. Keep fields terse — phrases not paragraphs. "
    "Do NOT invent details not present in the context."
)

CLASSIFY_PROMPT = """\
You manage a plan for a coding task.  Given the current plan items and the \
latest completed work, determine:

1. Which plan item the work belongs to (by index, 1-based)
2. An updated 1-2 sentence summary for that item
3. Whether the item's status should change
4. If the work substantially changed scope from the original label, provide an updated_label

Current plan:
{plan_block}

Latest completed work:
- Agent message: {agent_msg}
- Tools used: {tools}
- Tool intents: {intents}

Respond with JSON only:
{{"assign_to": <index>, "summary": "<brief summary of the specific work done>",
"status": "<active|done>", "updated_label": "<new label or null>"}}

RULES:
- assign_to is the 1-based index of the plan item this work belongs to.
- If the work clearly finishes this item, set status to "done".
- If work is ongoing, keep status as "active".
- Summary should describe what was specifically done. Be concrete: mention files, functions, endpoints.
- updated_label: only set when the work scope has clearly diverged from the
  original label (e.g. label says "scan" but agent actually fixed bugs).
  Use null when the original label is still accurate.  Concise and specific.
"""

INFER_PLAN_PROMPT = """\
A coding agent just started working on this task.  Based on the task \
description and the agent's first message, infer the natural steps for this task.

Task: {task}

Agent's first message:
{first_msg}

Respond with JSON only:
{{"items": ["Step 1 label", "Step 2 label", ...]}}

RULES:
- Each label: concise and specific.
- Cover the full task arc from start to finish.
- Be specific: mention files, components, endpoints where possible.
"""

TITLE_PROMPT = """\
You manage a progress timeline for a coding agent. Decide TWO things:
1. A short title for this turn
2. Whether this turn belongs to the current activity or starts a new one

Job task: {job_prompt}
Active plan item: {active_plan_label} ({done_count}/{total_count} plan items done)

Current activity and its steps so far:
{recent_step_titles}

This turn:
- Files read: {files_read}
- Files written: {files_written}
- Tools used: {tools}
- Duration: {duration_s}s
- Agent message: {agent_msg}

Context (recent transcript):
{preceding_context}

Respond with JSON:
{{"title": "...", "merge_with_previous": <bool>, "new_activity": <bool>, "activity_label": "..."}}

TITLE rules:
- 3-8 words, starts with action verb
- Never repeat previous step titles
- One thing per title, pick the most significant

new_activity: true when the agent's INTENT shifted — it's now working toward a
different sub-goal than the previous steps. Examples of shifts:
- Was reading/exploring → now editing/fixing
- Was working on module A → now working on unrelated module B
- Was fixing bugs → now writing docs
- Operator gave a new instruction

NOT a shift: continuing the same logical task across multiple turns (even if
touching different files), retrying, or verifying previous work.

activity_label: short label for the new activity (only used when new_activity=true).
3-6 words describing the sub-goal, e.g. "Fix inference bugs", "Clean up types".

merge_with_previous: true only for trivial retries of the exact same operation.
"""

REFINE_ACTIVITY_LABEL_PROMPT = """\
Refine this activity group label based on the completed work.

Current label: {current_label}
Steps completed:
{step_titles}

Generate a refined 3-7 word label that captures the theme of the work.
Be specific but brief. One main verb, one main object.

Good: "Fix inference tracking bugs"
Good: "Clean up type annotations"
Bad:  "Audited 22 files across 8 modules, identified 12+ code smells and 3 bugs"

Respond with JSON only:
{{"label": "<3-7 word refined label>"}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return text


def normalize_path(path: str) -> str:
    """Normalize a file path to repo-relative."""
    path = path.lstrip("./")
    if path.startswith("/"):
        path = path.lstrip("/")
    return path


def build_enrichment_prompt(
    nodes: list[TrailNodeRow],
    goal_intent: str | None,
    recent_decisions: list[TrailNodeRow],
) -> str:
    """Build the enrichment prompt for a batch of nodes."""
    import json

    parts: list[str] = []
    parts.append("AGENT TRAIL — annotate these trail nodes and detect semantic patterns.\n")

    if goal_intent:
        parts.append(f"CURRENT GOAL: {goal_intent}\n")

    parts.append("NODES TO ANNOTATE:")
    for node in nodes:
        files = json.loads(node.files) if node.files else []
        kind_note = ""
        if node.kind == "shell":
            kind_note = " (kind=shell means classification was uncertain — reclassify from transcript)"
        elif node.kind == "modify" and not files:
            kind_note = " (SHA divergence detected a write but we don't know which files)"
        parts.append(f"  - node_id: {node.id}, kind: {node.kind}, files: {files}{kind_note}")

    # Build per-node step context (now with transcript data)
    for node in nodes:
        parts.append(f"\nSTEP CONTEXT for node {node.id}:")
        if node.agent_message:
            parts.append(f"  Agent message: {node.agent_message}")
        if node.preceding_context:
            parts.append(f"  Preceding context: {node.preceding_context}")
        if node.tool_names:
            parts.append(f"  Tools used: {node.tool_names}")
        if node.intent:
            parts.append(f"  Current intent: {node.intent}")
        files = json.loads(node.files) if node.files else []
        if files:
            parts.append(f"  Files: {', '.join(files)}")
        if node.start_sha and node.end_sha and node.start_sha != node.end_sha:
            parts.append(f"  SHA changed: {node.start_sha} → {node.end_sha}")

    if recent_decisions:
        parts.append("\nRECENT DECISIONS (for supersedes linking):")
        for d in recent_decisions:
            parts.append(f"  - node_id: {d.id}, intent: {d.intent or '(pending)'}")

    parts.append(
        "\nRespond with JSON only. Two arrays:\n"
        '1. "annotations": [{node_id, kind, intent, rationale, outcome, files, tags}]\n'
        "   - For kind=modify or kind=explore: do NOT change the kind\n"
        "   - For kind=shell: reclassify to modify, explore, or verify\n"
        '2. "semantic_nodes": [{kind, intent, rationale, outcome, tags, supersedes, anchor_node_id}]\n'
        "   - kind must be one of: plan, insight, decide, backtrack, verify\n"
        "   - anchor_node_id = the node_id of the deterministic node this semantic node relates to\n"
        "   - supersedes = node_id of prior decide node being reversed (for backtrack/decide only)\n"
    )
    return "\n".join(parts)


def parse_enrichment_response(text: str) -> dict[str, Any] | None:
    """Parse LLM enrichment response."""
    import json

    text = strip_code_fences(text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        log.debug("enrichment_response_parse_failed", text_len=len(text))
        pass
    return None
