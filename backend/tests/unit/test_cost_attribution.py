from backend.services.cost_attribution import (
    _classify_turn_intent,
    _infer_execution_phases,
)
from backend.services.tool_classifier import classify_shell_command, classify_tool


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
    assert _classify_turn_intent(_ctx(cats=["git_write"])) == "git_ops"


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
    # Shell git reads are investigation, not git_ops
    assert _classify_turn_intent(_ctx(cats=["shell"], cmds=["git diff HEAD~1"])) == "investigation"


def test_classify_turn_intent_overhead() -> None:
    # Pure bookkeeping (report_intent, sql, memory, todos)
    assert _classify_turn_intent(_ctx(cats=["bookkeeping"])) == "overhead"
    assert _classify_turn_intent(_ctx(cats=["bookkeeping", "bookkeeping"])) == "overhead"


def test_classify_turn_intent_subagents_are_investigation() -> None:
    # Pure agent tool turns are classified as "investigation" — the per-tool
    # weighted path resolves the actual activity from sub-agent turns;
    # this fallback is conservative.
    assert _classify_turn_intent(_ctx(cats=["agent"])) == "investigation"


def test_classify_turn_intent_no_debugging_category() -> None:
    # File writes are always "implementation" regardless of job context
    assert _classify_turn_intent(_ctx(cats=["file_write"])) == "implementation"


def test_classify_turn_intent_communication_and_reasoning() -> None:
    # No tools, has output → communication
    assert _classify_turn_intent(_ctx(out_tok=500)) == "communication"
    # No tools, no output → reasoning
    assert _classify_turn_intent(_ctx(out_tok=0)) == "reasoning"
    # Thinking tool → reasoning
    assert _classify_turn_intent(_ctx(cats=["thinking"])) == "reasoning"


def test_classify_shell_command() -> None:
    # Verification: test runners
    assert classify_shell_command("pytest tests/") == "verification"
    assert classify_shell_command("uv run pytest -x") == "verification"
    assert classify_shell_command("npx jest --watch") == "verification"
    assert classify_shell_command("cargo test") == "verification"
    assert classify_shell_command("go test ./...") == "verification"
    assert classify_shell_command("npm test") == "verification"
    assert classify_shell_command("npm run test") == "verification"
    assert classify_shell_command("make test") == "verification"
    assert classify_shell_command("make lint") == "verification"
    # Verification: linters and type checkers
    assert classify_shell_command("mypy src/") == "verification"
    assert classify_shell_command("eslint .") == "verification"
    assert classify_shell_command("ruff check .") == "verification"
    assert classify_shell_command("tsc --noEmit") == "verification"
    # Verification: build commands
    assert classify_shell_command("npm run build") == "verification"
    assert classify_shell_command("cargo build") == "verification"
    assert classify_shell_command("go build ./...") == "verification"
    # Git write → git_ops
    assert classify_shell_command("git commit -m 'fix'") == "git_ops"
    assert classify_shell_command("git push origin main") == "git_ops"
    assert classify_shell_command("git add -A && git commit -m 'fix'") == "git_ops"
    # Git read → investigation (checkout/switch/stash are now read)
    assert classify_shell_command("git diff HEAD") == "investigation"
    assert classify_shell_command("git status") == "investigation"
    assert classify_shell_command("git log --oneline") == "investigation"
    assert classify_shell_command("git checkout main") == "investigation"
    assert classify_shell_command("git stash") == "investigation"
    # Setup
    assert classify_shell_command("uv sync") == "setup"
    assert classify_shell_command("pip install requests") == "setup"
    assert classify_shell_command("docker build -t foo .") == "setup"
    assert classify_shell_command("docker compose up -d") == "setup"
    # Investigation: exploration commands
    assert classify_shell_command("find . -name '*.py'") == "investigation"
    assert classify_shell_command("cat README.md") == "investigation"
    assert classify_shell_command("grep -r TODO .") == "investigation"
    # Implementation: file-modifying commands
    assert classify_shell_command("sed -i 's/old/new/' file.txt") == "implementation"
    assert classify_shell_command("rm -rf build/") == "implementation"
    assert classify_shell_command("mkdir -p src/foo") == "implementation"
    # Compound: highest priority wins
    assert classify_shell_command("cd src && pytest") == "verification"
    assert classify_shell_command("cat file.txt | grep foo") == "investigation"
    # Env vars stripped
    assert classify_shell_command("CI=1 pytest tests/") == "verification"
    assert classify_shell_command("PYTHONPATH=. uv run pytest") == "verification"
    # Unknown
    assert classify_shell_command("echo hello") == "shell_other"
    # False-positive guard: tool names as arguments don't match
    assert classify_shell_command("pip install pytest") == "setup"
    assert classify_shell_command("pip install jest") == "setup"


def test_classify_tool_list_agents() -> None:
    assert classify_tool("list_agents") == "agent"


def test_sql_classified_as_bookkeeping() -> None:
    assert classify_tool("sql") == "bookkeeping"
