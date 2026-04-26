"""Setup, preflight, and doctor for CodePlane.

Facade module that re-exports the public API from the split sub-modules
(``setup_checks``, ``setup_wizard``) and provides preflight / doctor
entry points plus their inline-fix helpers.
"""

from __future__ import annotations

import json as _json
import subprocess
from typing import Any

import questionary
from rich.panel import Panel

from backend.config import get_codeplane_dir, init_config, load_config, save_config

# Re-export everything that external callers import from this module.
from backend.services.setup_checks import (  # noqa: F401
    _SYSTEM,
    DEPENDENCIES,
    AgentAuthStatus,
    AgentCLIStatus,
    CheckResult,
    CheckStatus,
    Dependency,
    _console,
    _render_check_line,
    check_agent_cli,
    render_checks,
    render_summary,
    verify_requirements,
)
from backend.services.setup_wizard import (  # noqa: F401
    execute_setup_wizard,
)

# ---------------------------------------------------------------------------
# Inline fix helpers (used by preflight)
# ---------------------------------------------------------------------------

# Map (category, label-substring) → shell commands that can fix the issue.
_INLINE_FIX_COMMANDS: dict[str, list[str]] = {
    "claude_cli": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    "gh_auth": ["gh", "auth", "login"],
    "claude_auth": ["claude", "auth", "login"],
}


def _warning_sdk_id(warning: CheckResult) -> str | None:
    """Return the agent SDK id for an agent warning label."""
    if warning.category != "agent":
        return None
    if "Copilot" in warning.label:
        return "copilot"
    if "Claude" in warning.label:
        return "claude"
    return None


def _should_prompt_for_warning(warning: CheckResult, default_sdk: str, suppressed_agent_prompts: list[str]) -> bool:
    """Return whether preflight should stop and prompt for this warning.

    Once a non-default agent warning has been explicitly skipped and the
    current default agent is usable, later preflight runs should only log the
    warning instead of prompting again.
    """
    if warning.category != "agent":
        return False
    sdk_id = _warning_sdk_id(warning)
    if sdk_id is None:
        return True
    if sdk_id == default_sdk:
        return True
    if sdk_id not in suppressed_agent_prompts:
        return True
    return not check_agent_cli(default_sdk).ready


def _remember_skipped_warning(warning: CheckResult, default_sdk: str) -> None:
    """Persist that an inactive agent warning should not prompt again."""
    sdk_id = _warning_sdk_id(warning)
    if sdk_id is None or sdk_id == default_sdk:
        return
    if not check_agent_cli(default_sdk).ready:
        return

    config = load_config()
    if sdk_id in config.runtime.suppressed_preflight_agent_prompts:
        return
    config.runtime.suppressed_preflight_agent_prompts.append(sdk_id)
    save_config(config)


def _prompt_select(choices: list[questionary.Choice]) -> Any:  # noqa: ANN401
    """Present a selection prompt styled to match Rich preflight output.

    Uses a blank qmark, leading-space message, and the ``pointer`` style
    so the choices line up with the Rich check lines (2-space base indent).
    """
    return questionary.select(
        message="",
        qmark="",
        instruction="",
        pointer="  →",
        choices=choices,
    ).ask()


def _offer_inline_fix(warning: CheckResult) -> str:
    """Offer to fix a single preflight warning in-place.

    Returns one of: ``fixed``, ``skipped``, ``continued``.
    """
    # Determine which fix(es) apply
    fixes: list[tuple[str, list[str]]] = []

    if warning.category == "agent":
        cli = check_agent_cli("copilot" if "Copilot" in warning.label else "claude")
        if cli.sdk_id == "claude":
            if not cli.cli_reachable:
                fixes.append(("Install claude CLI", _INLINE_FIX_COMMANDS["claude_cli"]))
            else:
                # CLI is installed but auth may be missing
                auth = _check_agent_auth("claude")
                if auth.authenticated is not True:
                    fixes.append(("Authenticate claude CLI", _INLINE_FIX_COMMANDS["claude_auth"]))
        elif cli.sdk_id == "copilot":
            if not cli.cli_reachable:
                fixes.append(("Install GitHub CLI", ["gh", "auth", "login"]))
            else:
                auth = _check_agent_auth("copilot")
                if auth.authenticated is not True:
                    fixes.append(("Authenticate GitHub CLI", _INLINE_FIX_COMMANDS["gh_auth"]))

    if not fixes:
        # No automated fix available — just ask continue/abort
        choice = _prompt_select(
            [
                questionary.Choice("Continue anyway", value="continue"),
                questionary.Choice("Abort", value="abort"),
            ]
        )
        if choice == "abort" or choice is None:
            raise SystemExit(1)
        return "continued"

    # Offer to run the fix
    fix_choices = [questionary.Choice(f"Fix now  {' '.join(cmd)}", value=("fix", cmd)) for _label, cmd in fixes]
    fix_choices.append(questionary.Choice("Skip", value=("skip", [])))
    fix_choices.append(questionary.Choice("Abort", value=("abort", [])))

    choice = _prompt_select(fix_choices)

    if choice is None or choice[0] == "abort":
        raise SystemExit(1)
    if choice[0] == "skip":
        return "skipped"

    # Attempt the fix
    _, cmd = choice
    _console.print(f"       [dim]Running {' '.join(cmd)} …[/dim]")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return "fixed"
        _console.print(f"       [red]Failed (exit {result.returncode})[/red]")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[:3]:
                _console.print(f"       [dim]{line}[/dim]")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _console.print(f"       [red]Failed: {exc}[/red]")

    # Auto-fix failed — give manual instructions and a recheck option
    _console.print()
    _console.print("       [yellow]Could not install automatically.[/yellow]")
    _console.print("       [dim]Fix it in another terminal:[/dim]")
    for _label, fix_cmd in fixes:
        _console.print(f"       [cyan]{' '.join(fix_cmd)}[/cyan]")
    _console.print()

    retry = _prompt_select(
        [
            questionary.Choice("I've fixed it — recheck", value="recheck"),
            questionary.Choice("Continue anyway", value="continue"),
            questionary.Choice("Abort", value="abort"),
        ]
    )

    if retry == "abort" or retry is None:
        raise SystemExit(1)
    if retry == "recheck":
        if warning.category == "agent":
            rechecked = check_agent_cli("copilot" if "Copilot" in warning.label else "claude")
            if rechecked.ready:
                return "fixed"
            _console.print(f"       [yellow]Still not resolved: {rechecked.detail}[/yellow]")
        return "continued"
    # "continue"
    return "continued"


# ---------------------------------------------------------------------------
# cpl up — preflight
# ---------------------------------------------------------------------------


def validate_preflight(port: int) -> bool:
    """Interactive preflight for ``cpl up``.

    Returns True if the server can start.
    On warnings, pauses to let the user fix issues or continue.
    """
    config = load_config()
    results = verify_requirements(port=port, include_optional_dependencies=False, preflight=True)

    _console.print()
    _console.print("  [bold]Preflight[/bold]")
    _console.print()
    for r in results:
        _render_check_line(r)

    has_fail = any(r.status == CheckStatus.fail for r in results)
    warnings = [r for r in results if r.status == CheckStatus.warn]

    # Auto-create config on first run
    config_path = get_codeplane_dir() / "config.yaml"
    if not config_path.exists():
        init_config()
        _console.print()
        _console.print("  [dim]Created default config at[/dim]", str(config_path))

    if has_fail:
        _console.print()
        _console.print("  [red bold]Cannot start — fix the errors above.[/red bold]")
        _console.print("  [dim]Run 'cpl setup' for guided installation, or 'cpl doctor' for details.[/dim]")
        return False

    if warnings:
        _console.print()
        _console.print(f"  [yellow bold]{len(warnings)} issue{'s' if len(warnings) != 1 else ''} found:[/yellow bold]")

        for w in warnings:
            _console.print()
            _console.print(f"    [yellow]![/yellow]  [bold]{w.label}[/bold]: {w.detail}")
            if w.hint:
                for line in w.hint.split("\n"):
                    _console.print(f"       → {line}")

            if not _should_prompt_for_warning(
                w,
                config.runtime.default_sdk,
                config.runtime.suppressed_preflight_agent_prompts,
            ):
                _console.print("       [dim]Prompt suppressed by config; continuing with current default agent.[/dim]")
                continue

            outcome = _offer_inline_fix(w)
            if outcome == "fixed":
                _console.print(f"    [green]✓[/green]  {w.label}: fixed")
            elif outcome == "skipped":
                _remember_skipped_warning(w, config.runtime.default_sdk)

        # Re-check for any remaining hard failures after fixes
        results = verify_requirements(port=port, include_optional_dependencies=False, preflight=True)
        if any(r.status == CheckStatus.fail for r in results):
            _console.print()
            _console.print("  [red bold]Cannot start — fix the errors above.[/red bold]")
            return False

    _console.print()
    return True


# ---------------------------------------------------------------------------
# cpl doctor — non-interactive diagnostic
# ---------------------------------------------------------------------------


def diagnose_configuration(*, as_json: bool = False) -> bool:
    """Full non-interactive diagnostic.

    Returns True if no hard failures.
    """
    results = verify_requirements(port=load_config().server.port)

    if as_json:
        data = {
            "checks": [
                {
                    "label": check.label,
                    "status": check.status.value,
                    "detail": check.detail,
                    "hint": check.hint,
                    "category": check.category,
                }
                for check in results
            ],
            "passed": sum(1 for check in results if check.status == CheckStatus.passed),
            "warnings": sum(1 for check in results if check.status == CheckStatus.warn),
            "failed": sum(1 for check in results if check.status == CheckStatus.fail),
        }
        print(_json.dumps(data, indent=2))  # noqa: T201
        return not any(check.status == CheckStatus.fail for check in results)

    _console.print()
    _console.print(Panel("[bold]CodePlane Doctor[/bold]", border_style="cyan", expand=False))

    render_checks(results, grouped=True)
    render_summary(results)

    has_fail = any(r.status == CheckStatus.fail for r in results)
    if has_fail:
        _console.print()
        _console.print("  [red]Fix required — run 'cpl setup' to resolve.[/red]")
    else:
        _console.print()
        _console.print("  [green]All clear — run 'cpl up' to start.[/green]")
    _console.print()

    return not has_fail
