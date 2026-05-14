"""Prompt templates for plan-mode execution.

The planning session receives only the task and produces a structured plan
via manage_todo_list.  The implementation session receives a handoff prompt
containing the approved plan and the preflight curator's curated context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models.domain import Job

_PLANNING_PROMPT = """\
## Task

{task}

## Instructions

Analyze the codebase and produce an execution plan for this task.
Use the manage_todo_list tool to submit your plan as a structured list of items.
Each item should be a concrete work unit — mention specific files, modules, \
endpoints, or components where possible.

After submitting your plan, stop. Do not implement anything.\
"""

_IMPLEMENTATION_HANDOFF = """\
## Task

{task}

## Approved Plan

{plan}
{operator_section}\

## Instructions

Execute the plan above. The plan has been reviewed and approved by the operator.
Work through each item in order. Use manage_todo_list to track your progress \
as you complete each item.\
"""

_REPLAN_PROMPT = """\
## Task

{task}

## Previous Plan (Rejected)

{previous_plan}

## Operator Feedback

{feedback}

## Instructions

Revise your plan based on the operator's feedback above.
Use the manage_todo_list tool to submit the revised plan, then stop.
Do not implement anything.\
"""


def build_planning_prompt(job: Job) -> str:
    """Build the prompt for the planning session."""
    return _PLANNING_PROMPT.format(task=job.prompt)


def build_implementation_handoff(
    job: Job,
    plan_text: str,
    *,
    curated_context: str = "",
    operator_notes: str = "",
) -> str:
    """Build the handoff prompt for the implementation session.

    *curated_context* is the preflight curator output from the planning
    session — injected as ``memory_context`` on the implementation
    ``SessionConfig`` rather than inlined in the prompt (the adapter
    appends it as a ``## Workspace Memory`` section).

    *operator_notes* are optional notes the operator attached to the
    plan approval.
    """
    operator_section = ""
    if operator_notes:
        operator_section = f"\n## Operator Notes\n\n{operator_notes}\n"

    return _IMPLEMENTATION_HANDOFF.format(
        task=job.prompt,
        plan=plan_text,
        operator_section=operator_section,
    )


def build_replan_prompt(job: Job, previous_plan: str, feedback: str) -> str:
    """Build the prompt for a re-planning session after plan rejection."""
    return _REPLAN_PROMPT.format(
        task=job.prompt,
        previous_plan=previous_plan,
        feedback=feedback,
    )


def format_plan_text(steps: list[dict[str, str]]) -> str:
    """Format plan steps into a numbered text list for prompt injection."""
    lines = []
    for i, step in enumerate(steps, 1):
        label = step.get("label") or step.get("title") or f"Step {i}"
        lines.append(f"{i}. {label}")
    return "\n".join(lines)
