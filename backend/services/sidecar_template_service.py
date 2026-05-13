"""Sidecar template service — CRUD and LLM-assisted generation."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.persistence.sidecar_template_repo import SidecarTemplateRepository
    from backend.services.sidecar_session import SidecarSessionManager

from backend.models.domain import SidecarTemplate

log = structlog.get_logger()

# Context sources available to custom sidecars (safe subset).
_ALLOWED_CONTEXT_SOURCES = ["trigger_event", "job_diff", "job_prompt", "recent_messages"]

# Output routes available to custom sidecars.
_ALLOWED_OUTPUT_ROUTES = ["event_bus", "job_metadata", "agent_message", "gate"]

# Trigger conditions available to custom sidecars.
_ALLOWED_CONDITIONS = ["event", "threshold", "manual", "regex", "file_pattern", "content_match"]

# Allowed phases, lifetimes, and scopes.
_ALLOWED_PHASES = ["preflight", "midflight", "postflight"]
_ALLOWED_LIFETIMES = ["ephemeral", "windowed", "persistent"]
_ALLOWED_SCOPES = ["global", "repo", "job"]

_GENERATE_SYSTEM_PROMPT = """\
You are a sidecar definition generator for CodePlane, a coding agent control plane.

A sidecar is an autonomous LLM session that runs alongside a coding agent job.
Given a natural-language description of what the user wants the sidecar to do,
produce a valid sidecar definition as a JSON object.

Available fields:
- "name": kebab-case identifier (e.g. "security-reviewer"). Required.
- "description": Short human-readable summary, 1-2 sentences. Required.
- "icon": Choose one icon name that represents this sidecar's purpose. Available icons:
  shield, eye, search, zap, brain, target, flask, bug, lock, key, compass,
  gauge, microscope, alarm, bookmark, clipboard, filter, flag, heart, lightbulb,
  megaphone, palette, radar, satellite, scanner, scale, siren, telescope, wand.
  Required.
- "scope": Where this sidecar applies. One of: "global", "repo", "job". Default "global".
  - "global": applies to all jobs across all repos — best for universal policies (security reviews, style enforcement, cost monitoring).
  - "repo": applies to all jobs in a specific repo — best for repo-specific conventions (migration reviewers, test coverage for a monorepo).
  - "job": applies to a single job — best for one-off or task-specific sidecars (review this PR, audit this refactor).
  Choose based on how broadly the sidecar's purpose applies. When in doubt, prefer "global".
- "phase": When the sidecar runs. One of: "preflight", "midflight", "postflight". Required.
- "lifetime": How long the session lives. One of: "ephemeral", "windowed", "persistent". Required.
  - For "windowed": also include "maxTurns" (int, optional) and/or "timeoutS" (float, optional) to define window bounds.
- "model": LLM model to use. Pick the cheapest viable option for the task complexity:
  - Simple classification/extraction: "gpt-4o-mini" (cheapest)
  - Moderate analysis: "claude-sonnet-4-20250514" or "gpt-4o"
  - Complex reasoning/review: "claude-sonnet-4-20250514"
  If omitted, defaults to the system utility model. Optional.
- "systemPrompt": The system prompt for the sidecar LLM session. Required.
- "triggers": Array of trigger pipeline objects. Required, at least one.

Each trigger object has:
- "condition": {"kind": "<kind>"} where kind is one of: "event", "threshold", "manual", "regex", "file_pattern", "content_match".
  - event conditions: {"kind": "event", "eventKind": "<event_type>"}
  - threshold conditions: {"kind": "threshold", "metric": "messages"|"tool_calls", "value": <int>}
  - manual conditions: {"kind": "manual"}
  - regex conditions: {"kind": "regex", "pattern": "<regex>", "source": "messages"|"tool_calls"|"tool_output"}. Named capture groups become template variables.
  - file_pattern conditions: {"kind": "file_pattern", "glob": "<glob>", "changeKind": "any"|"added"|"modified"|"deleted"}. Fires when changed files match the glob.
  - content_match conditions: {"kind": "content_match", "keywords": ["<word>", ...], "caseSensitive": false}. Fires when agent output contains any keyword.
- "contextSources": Array of context provider names. Available: "trigger_event", "job_diff", "job_prompt", "recent_messages".
- "promptTemplate": Jinja-style template string with {variable} placeholders matching context source keys.
- "outputParser": {"kind": "plain_text"} or {"kind": "json_object"} or {"kind": "json_array"}.
- "outputRoutes": Array of route objects:
  - {"kind": "event_bus", "eventKind": "<custom_event_name>"}
  - {"kind": "job_metadata", "field": "<metadata_field_name>"}
  - {"kind": "agent_message"} — inject a message into the agent's conversation. Optional "role": "system"|"tool_result", "label": "<prefix>".
  - {"kind": "gate", "verdictField": "verdict", "reasonField": "reason"} — block agent until sidecar approves. Parsed output must contain verdict ("approve"|"reject") and optional reason. Optional "timeoutS": <seconds>.

Guidelines:
- For code review tasks, use phase "postflight" with manual trigger and "job_diff" context.
- For monitoring tasks (watching progress), use phase "midflight" with threshold triggers.
- For pattern-matching tasks (detecting phrases, bad patterns), use regex or content_match conditions.
- For file-type-specific reviews (SQL migrations, configs), use file_pattern conditions.
- For one-shot analysis, use lifetime "ephemeral". For ongoing monitoring, use "persistent".
- When the sidecar should influence the agent's behavior, use "agent_message" to send feedback.
- When the sidecar must approve/block agent actions, use "gate" with a json_object output parser that returns {"verdict": "approve"|"reject", "reason": "..."}.
- Keep system prompts focused and actionable.
- Generate a descriptive but concise name in kebab-case.

Respond with ONLY a valid JSON object, no markdown fences, no explanation.
"""

_GENERATE_USER_PROMPT = """\
Create a sidecar definition for the following request:

{description}
"""


class SidecarTemplateService:
    """Manages the sidecar template library and LLM-assisted generation."""

    def __init__(
        self,
        repo: SidecarTemplateRepository,
        sidecar_sessions: SidecarSessionManager,
    ) -> None:
        self._repo = repo
        self._sidecar_sessions = sidecar_sessions

    async def list_templates(self) -> list[SidecarTemplate]:
        """List all saved sidecar templates."""
        return await self._repo.list_all()

    async def get_template(self, template_id: str) -> SidecarTemplate | None:
        """Get a single template by ID."""
        return await self._repo.get(template_id)

    async def create_template(
        self,
        *,
        name: str,
        description: str,
        definition_json: str,
    ) -> SidecarTemplate:
        """Create and save a new sidecar template."""
        _validate_definition(definition_json)
        existing = await self._repo.get_by_name(name)
        if existing:
            raise ValueError(f"A template named {name!r} already exists")
        template = SidecarTemplate(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            definition_json=definition_json,
            created_at=datetime.now(UTC),
        )
        return await self._repo.create(template)

    async def update_template(
        self,
        template_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        definition_json: str | None = None,
    ) -> SidecarTemplate | None:
        """Update an existing template. Returns None if not found."""
        if definition_json is not None:
            _validate_definition(definition_json)
        if name is not None:
            existing = await self._repo.get_by_name(name)
            if existing and existing.id != template_id:
                raise ValueError(f"A template named {name!r} already exists")
        return await self._repo.update(
            template_id,
            name=name,
            description=description,
            definition_json=definition_json,
        )

    async def delete_template(self, template_id: str) -> bool:
        """Delete a template. Returns True if removed."""
        return await self._repo.delete(template_id)

    async def touch_last_used(self, template_id: str) -> None:
        """Mark a template as recently used."""
        await self._repo.touch_last_used(template_id, datetime.now(UTC))

    async def generate_definition(self, description: str) -> dict:
        """Use an LLM to generate a sidecar definition from a natural language description.

        Returns the parsed JSON definition dict.
        """
        prompt = (
            _GENERATE_SYSTEM_PROMPT
            + "\n\n"
            + _GENERATE_USER_PROMPT.format(description=description)
        )
        raw = await self._sidecar_sessions.complete(prompt)
        if not raw:
            raise ValueError("Empty response from LLM")

        text = _strip_markdown_fences(raw.strip())

        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("sidecar_generate_invalid_json", response_length=len(text))
            raise ValueError("LLM returned invalid JSON") from exc

        if not isinstance(definition, dict):
            raise ValueError("LLM returned non-object JSON")

        # Ensure required fields exist
        if "name" not in definition:
            raise ValueError("Generated definition missing 'name'")
        if "description" not in definition:
            definition["description"] = description[:200]

        _validate_definition(json.dumps(definition))

        log.info(
            "sidecar_definition_generated",
            name=definition.get("name"),
        )
        return definition


def _strip_markdown_fences(text: str) -> str:
    """Extract JSON from markdown code fences if present."""
    if not text.startswith("```"):
        return text
    # Find content between first ``` line and last ```
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    last_fence = text.rfind("```", first_newline)
    if last_fence <= first_newline:
        return text[first_newline + 1 :].strip()
    return text[first_newline + 1 : last_fence].strip()


def _validate_definition(definition_json: str) -> None:
    """Validate a sidecar definition JSON string.

    Raises ValueError on invalid structure or disallowed values.
    """
    try:
        defn = json.loads(definition_json)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in definition") from exc

    if not isinstance(defn, dict):
        raise ValueError("Definition must be a JSON object")

    # Required top-level fields
    for field in ("phase", "lifetime", "systemPrompt", "triggers"):
        if field not in defn:
            raise ValueError(f"Missing required field: {field!r}")

    scope = defn.get("scope", "global")
    if scope not in _ALLOWED_SCOPES:
        raise ValueError(
            f"Invalid scope {scope!r}. Allowed: {_ALLOWED_SCOPES}"
        )
    if defn["phase"] not in _ALLOWED_PHASES:
        raise ValueError(
            f"Invalid phase {defn['phase']!r}. Allowed: {_ALLOWED_PHASES}"
        )
    if defn["lifetime"] not in _ALLOWED_LIFETIMES:
        raise ValueError(
            f"Invalid lifetime {defn['lifetime']!r}. Allowed: {_ALLOWED_LIFETIMES}"
        )
    if not isinstance(defn["systemPrompt"], str) or not defn["systemPrompt"].strip():
        raise ValueError("systemPrompt must be a non-empty string")

    triggers = defn["triggers"]
    if not isinstance(triggers, list) or len(triggers) == 0:
        raise ValueError("triggers must be a non-empty array")

    for i, trigger in enumerate(triggers):
        if not isinstance(trigger, dict):
            raise ValueError(f"triggers[{i}] must be an object")

        # Validate context sources
        for source in trigger.get("contextSources", []):
            if source not in _ALLOWED_CONTEXT_SOURCES:
                raise ValueError(
                    f"Context source {source!r} is not allowed for custom sidecars. "
                    f"Allowed: {_ALLOWED_CONTEXT_SOURCES}"
                )

        # Validate output routes
        for route in trigger.get("outputRoutes", []):
            kind = route.get("kind")
            if kind not in _ALLOWED_OUTPUT_ROUTES:
                raise ValueError(
                    f"Output route kind {kind!r} is not allowed for custom sidecars. "
                    f"Allowed: {_ALLOWED_OUTPUT_ROUTES}"
                )

        # Validate trigger conditions
        condition = trigger.get("condition", {})
        cond_kind = condition.get("kind")
        if cond_kind and cond_kind not in _ALLOWED_CONDITIONS:
            raise ValueError(
                f"Trigger condition {cond_kind!r} is not allowed for custom sidecars. "
                f"Allowed: {_ALLOWED_CONDITIONS}"
            )
