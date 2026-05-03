from backend.services.cost_attribution import (
    _classify_turn_intent,
    _classify_shell_command,
    _infer_execution_phases,
)
from backend.services.tool_classifier import classify_tool


def test_infer_execution_phases_uses_neighboring_valid_phases() -> None:
    spans = [
        {"execution_phase": None},
        {"execution_phase": "agent_reasoning"},
        {"execution_phase": None},
        {"execution_phase": "verification"},
        {"execution_phase": None},
    ]

    assert _infer_execution_phases(spans) == [
        "agent_reasoning",
        "agent_reasoning",
        "agent_reasoning",
        "verification",
        "verification",
    ]


def test_infer_execution_phases_does_not_invent_unknown_bucket() -> None:
    spans = [
        {"execution_phase": None},
        {"execution_phase": "unknown"},
    ]

    assert _infer_execution_phases(spans) == [None, None]


def _ctx(*, cats: list[str] | None = None, cmds: list[str] | None = None, out_tok: int = 0) -> dict:
    """Build a minimal TurnContext dict for testing."""
    return {
        "phase": None,
        "cost_usd": 1.0,
        "input_tokens": 100,
        "output_tokens": out_tok,
        "tool_categories": cats or [],
        "shell_commands": cmds or [],
    }


def test_classify_turn_intent_implementation_wins() -> None:
    # Turns with file writes are always implementation, even if also reading
    assert _classify_turn_intent(_ctx(cats=["file_write"])) == "implementation"
    assert _classify_turn_intent(_ctx(cats=["file_read", "file_read", "file_write"])) == "implementation"
    assert _classify_turn_intent(_ctx(cats=["file_read", "file_write", "shell"], cmds=["git diff"])) == "implementation"
    assert _classify_turn_intent(_ctx(cats=["git_write"])) == "implementation"


def test_classify_turn_intent_verification() -> None:
    # Shell commands running tests → verification
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["pytest tests/"])) == "verification"
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["npm test"])) == "verification"
    assert _classify_turn_intent(_ctx(cats=["shell", "file_read"], cmds=["vitest run"])) == "verification"


def test_classify_turn_intent_git_ops() -> None:
    # Git write commands (commit, push)
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["git add -A && git commit -m 'fix'"])) == "git_ops"
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["git push origin main"])) == "git_ops"


def test_classify_turn_intent_setup() -> None:
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["uv sync"])) == "setup"
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["npm install"])) == "setup"
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["pip install requests"])) == "setup"


def test_classify_turn_intent_investigation() -> None:
    # Pure reading turns
    assert _classify_turn_intent(_ctx(cats=["file_read"])) == "investigation"
    assert _classify_turn_intent(_ctx(cats=["file_read", "file_read", "file_search"])) == "investigation"
    assert _classify_turn_intent(_ctx(cats=["git_read"])) == "investigation"
    assert _classify_turn_intent(_ctx(cats=["browser"])) == "investigation"
    # Shell commands that explore
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["find . -name '*.py'"])) == "investigation"
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["git diff HEAD~1"])) == "investigation"


def test_classify_turn_intent_overhead() -> None:
    # Pure bookkeeping (report_intent, sql, memory, todos)
    assert _classify_turn_intent(_ctx(cats=["bookkeeping"])) == "overhead"
    assert _classify_turn_intent(_ctx(cats=["bookkeeping", "bookkeeping"])) == "overhead"


def test_classify_turn_intent_delegation() -> None:
    assert _classify_turn_intent(_ctx(cats=["agent"])) == "delegation"


def test_classify_turn_intent_communication_and_reasoning() -> None:
    # No tools, has output → communication
    assert _classify_turn_intent(_ctx(out_tok=500)) == "communication"
    # No tools, no output → reasoning
    assert _classify_turn_intent(_ctx(out_tok=0)) == "reasoning"
    # Thinking tool → reasoning
    assert _classify_turn_intent(_ctx(cats=["thinking"])) == "reasoning"


def test_classify_shell_command() -> None:
    assert _classify_shell_command("pytest tests/") == "verification"
    assert _classify_shell_command("git commit -m 'fix'") == "git_ops"
    assert _classify_shell_command("uv sync") == "setup"
    assert _classify_shell_command("git diff HEAD") == "investigation"
    assert _classify_shell_command("find . -name '*.py'") == "investigation"
    assert _classify_shell_command("echo hello") == "shell_other"


def test_classify_tool_list_agents() -> None:
    assert classify_tool("list_agents") == "agent"


def test_sql_classified_as_bookkeeping() -> None:
    assert classify_tool("sql") == "bookkeeping"
