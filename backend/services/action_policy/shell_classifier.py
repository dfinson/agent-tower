"""Shell command classifier — returns (reversible, contained) for shell commands.

Architecture:
  classify_shell() orchestrates sh-guard (AST) + a chain of classifier functions.
  sh-guard handles: compound decomposition, injection/taint detection.
  Classifier chain handles: tool tables, localhost checks, wrapper unwrapping.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from typing import Any

from sh_guard import classify as sh_guard_classify

log = logging.getLogger(__name__)


# ── Classification outcomes ──────────────────────────────────────────────
#
# Every classifier returns one of these four tuples or None (= pass).
# Named constants so the intent reads at the call site.

_OBSERVE = (True, True)  # reversible + contained → observe tier
_UNCONTAINED = (True, False)  # reversible + network → gate in all presets
_IRREVERSIBLE = (False, True)  # irreversible + contained → gate in supervised
_BLOCKED = (False, False)  # irreversible + network → gate everywhere

#: Return type for individual classifiers.  None = "not my jurisdiction".
_Result = tuple[bool, bool] | None


# ═══════════════════════════════════════════════════════════════════════════
# Data tables — pure declarations, no logic
# ═══════════════════════════════════════════════════════════════════════════

# ── POSIX ─────────────────────────────────────────────────────────────────

_POSIX_OBSERVE = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "wc",
        "echo",
        "pwd",
        "printenv",
        "whoami",
        "date",
        "file",
        "stat",
        "du",
        "tree",
        "diff",
        "more",
        "less",
        "which",
        "type",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "test",
        "true",
        "false",
    }
)

#: Transparent wrappers pass through to a wrapped command.
_TRANSPARENT_WRAPPERS = frozenset(
    {
        "env",
        "nice",
        "timeout",
        "stdbuf",
        "nohup",
        "command",
    }
)

_POSIX_UNCONTAINED = frozenset(
    {
        "curl",
        "wget",
        "ssh",
        "scp",
        "rsync",
        "nc",
        "ncat",
        "telnet",
        "ftp",
        "sftp",
        "sendmail",
        "mail",
        "socat",
        "nmap",
        "dig",
        "nslookup",
        "host",
    }
)

_POSIX_IRREVERSIBLE = frozenset(
    {
        "rm",
        "shred",
        "dd",
        "mkfs",
        "fdisk",
        "kill",
        "killall",
        "pkill",
        "shutdown",
        "reboot",
        "halt",
    }
)

_POSIX_TEE = frozenset({"tee"})

_POSIX_CONDITIONALLY_SAFE = frozenset({"find", "sort"})

_TEST_RUNNERS = frozenset(
    {
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "ava",
        "tap",
        "bats",
        "phpunit",
        "rspec",
        "minitest",
    }
)

_TEST_SUBCOMMAND_BINARIES = frozenset(
    {
        "go",
        "dotnet",
        "swift",
        "mix",
        "elixir",
    }
)

_INTERPRETERS = frozenset(
    {
        "python",
        "python3",
        "node",
        "ruby",
        "perl",
        "bash",
        "sh",
        "zsh",
    }
)

_CODE_EXEC_PRIMITIVES = frozenset(
    {
        "eval",
        "exec",
        "source",
        ".",
    }
)

_BUILD_TOOLS = frozenset(
    {
        "make",
        "cmake",
        "gradle",
        "mvn",
        "ant",
    }
)

_PROXY_ENV_VARS = frozenset(
    {
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ftp_proxy",
    }
)

# ── PowerShell ────────────────────────────────────────────────────────────

_PS_OBSERVE_VERBS = frozenset(
    {
        "Get",
        "Find",
        "Search",
        "Test",
        "Measure",
        "Compare",
        "Select",
        "Format",
        "Out",
        "Show",
        "Read",
        "Watch",
        "Write",
    }
)

_PS_MUTATING_VERBS = frozenset(
    {
        "Set",
        "New",
        "Add",
        "Remove",
        "Clear",
        "Move",
        "Rename",
        "Copy",
        "Update",
        "Reset",
        "Enable",
        "Disable",
    }
)

_PS_UNCONTAINED_VERBS = frozenset(
    {
        "Send",
        "Connect",
        "Disconnect",
        "Publish",
        "Push",
        "Invoke-Web",
    }
)

# ── cmd.exe ───────────────────────────────────────────────────────────────

_CMD_OBSERVE = frozenset(
    {
        "dir",
        "type",
        "echo",
        "set",
        "ver",
        "where",
        "findstr",
        "find",
        "more",
        "tree",
        "path",
        "vol",
    }
)

_CMD_IRREVERSIBLE = frozenset(
    {
        "del",
        "erase",
        "rmdir",
        "rd",
        "format",
    }
)

# ── Cross-platform tool subcommand tables ─────────────────────────────────
#
# Each entry maps subcommand → (reversible, contained).

_GIT_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "status": _OBSERVE,
    "log": _OBSERVE,
    "diff": _OBSERVE,
    "show": _OBSERVE,
    "branch": _OBSERVE,
    "stash": _OBSERVE,
    "add": _OBSERVE,
    "commit": _OBSERVE,
    "checkout": _OBSERVE,
    "switch": _OBSERVE,
    "restore": _OBSERVE,
    "revert": _OBSERVE,
    "tag": _OBSERVE,
    "remote": _OBSERVE,
    "merge": _OBSERVE,
    "rebase": _OBSERVE,
    "cherry-pick": _OBSERVE,
    "reset": _OBSERVE,  # default; --hard overridden by flag check
    "fetch": _UNCONTAINED,
    "pull": _UNCONTAINED,
    "push": _UNCONTAINED,
    "clone": _UNCONTAINED,
    "force-push": _BLOCKED,
    "clean": _IRREVERSIBLE,
}

_NPM_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install": _OBSERVE,
    "ci": _OBSERVE,
    "test": _OBSERVE,
    "build": _OBSERVE,
    "link": _OBSERVE,
    "uninstall": _OBSERVE,
    "run": _IRREVERSIBLE,  # executes arbitrary scripts from package.json
    "start": _IRREVERSIBLE,  # delegates to scripts.start
    "publish": _BLOCKED,
    "unpublish": _BLOCKED,
}

_CARGO_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build": _OBSERVE,
    "test": _OBSERVE,
    "check": _OBSERVE,
    "clippy": _OBSERVE,
    "fmt": _OBSERVE,
    "install": _OBSERVE,
    "run": _IRREVERSIBLE,  # compiles + runs arbitrary code
    "publish": _BLOCKED,
}

_DOCKER_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build": _OBSERVE,
    "ps": _OBSERVE,
    "images": _OBSERVE,
    "logs": _OBSERVE,
    "rm": _OBSERVE,
    "rmi": _OBSERVE,
    "stop": _OBSERVE,
    "start": _OBSERVE,
    "compose": _OBSERVE,
    "run": _IRREVERSIBLE,  # default; flag inspection may escalate
    "exec": _IRREVERSIBLE,
    "pull": _UNCONTAINED,
    "push": _BLOCKED,
}

_PIP_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install": _OBSERVE,
    "uninstall": _OBSERVE,
    "list": _OBSERVE,
    "show": _OBSERVE,
    "freeze": _OBSERVE,
}

_UV_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "sync": _OBSERVE,
    "add": _OBSERVE,
    "remove": _OBSERVE,
    "lock": _OBSERVE,
    "pip": _OBSERVE,
    "run": _BLOCKED,  # Turing-complete: uv run python/curl/bash
    "publish": _BLOCKED,
}

_CROSS_PLATFORM_TOOLS: dict[str, dict[str, tuple[bool, bool]]] = {
    "git": _GIT_SUBCOMMANDS,
    "npm": _NPM_SUBCOMMANDS,
    "npx": dict(_NPM_SUBCOMMANDS),
    "yarn": _NPM_SUBCOMMANDS,
    "pnpm": _NPM_SUBCOMMANDS,
    "cargo": _CARGO_SUBCOMMANDS,
    "docker": _DOCKER_SUBCOMMANDS,
    "pip": _PIP_SUBCOMMANDS,
    "pip3": _PIP_SUBCOMMANDS,
    "uv": _UV_SUBCOMMANDS,
}


# ── Regex patterns ────────────────────────────────────────────────────────

_DEV_TCP_RE = re.compile(r"/dev/(?:tcp|udp)/", re.IGNORECASE)

_PIP_REMOTE_RE = re.compile(
    r"(?:git\+https?://|https?://\S+\.(?:tar\.gz|whl|zip))",
    re.IGNORECASE,
)

_FIND_DANGEROUS_RE = re.compile(
    r"(?:^|\s)(?:-exec|-execdir|-delete|-ok|-okdir)\b",
)

_SORT_OUTPUT_RE = re.compile(r"(?:^|\s)-o\b|(?:^|\s)--output(?:=|\s)")

_DOCKER_ESCAPE_RE = re.compile(
    r"--privileged\b"
    r"|--net(?:work)?[= ]host\b"
    r"|--pid[= ]host\b"
    r"|--cap-add[= ]\S*(?:ALL|SYS_ADMIN)\b"
    r"|(?:^|\s)(?:-v\s+|--volume[= ])/:?"
    r"|(?:^|\s)(?:-v\s+|--volume[= ])/[^: ]+:",
    re.IGNORECASE,
)

_GIT_RESET_HARD_RE = re.compile(
    r"\bgit\s+reset\b[^|;&\n]*?\s--hard\b",
    re.IGNORECASE,
)

_GIT_PUSH_FORCE_RE = re.compile(
    r"\bgit\s+push\b[^|;&\n]*?\s(?:--force\b|-f\b|--force-with-lease\b)",
    re.IGNORECASE,
)

_PS_CMDLET_RE = re.compile(r"^([A-Z][a-z]+)-", re.IGNORECASE)

_LOCALHOST_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|::1|\[::1\]|0\.0\.0\.0)(?::\d+)?",
    re.IGNORECASE,
)

_CURL_MUTATING_RE = re.compile(
    r"""
    -X\s*(?:POST|PUT|DELETE|PATCH)
    | --request\s+(?:POST|PUT|DELETE|PATCH)
    | --data(?:-\w+)?\b
    | -d\s
    | --upload-file\b
    | -T\s
    | -F\s
    | --form\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_URL_HOST_RE = re.compile(
    r"(?:https?://|//)([a-zA-Z0-9._-]+(?::\d+)?)",
)

# sh-guard risk factors that indicate injection/exfiltration — fail-closed.
_INJECTION_RISKS = frozenset(
    {
        "command_substitution",  # $(cmd) / `cmd`
        "network_exfiltration",  # pipeline taint to network
        "process_substitution",  # <(cmd) as FD source
        "path_injection",  # PATH= shadows safe binaries
        "obfuscated_command",  # $'\x24(...)' encoding tricks
        "command_execution",  # eval/source
    }
)


# ═══════════════════════════════════════════════════════════════════════════
# Parsing utilities
# ═══════════════════════════════════════════════════════════════════════════


def _shlex_split(command: str) -> list[str]:
    """shlex.split with fallback to naive split on parse errors."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _extract_binary_and_sub(cmd: str) -> tuple[str, str | None]:
    """Extract the binary name (lowercased, no path) and first subcommand."""
    stripped = cmd.strip()
    # Skip leading environment variable assignments (FOO=bar cmd ...)
    while stripped.split() and "=" in stripped.split()[0]:
        stripped = stripped.split(None, 1)[1] if " " in stripped else ""

    parts = _shlex_split(stripped)
    if not parts:
        return "", None

    binary = os.path.basename(parts[0]).lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".sh"):
        if binary.endswith(suffix):
            binary = binary[: -len(suffix)]

    subcmd = parts[1] if len(parts) > 1 and not parts[1].startswith("-") else None
    return binary, subcmd


def _is_path_qualified(command: str) -> bool:
    """Check if the binary is path-qualified (./cmd, /path/to/cmd, ../cmd).

    Path-qualified binaries can shadow safe OBSERVE tools with trojans.
    Skips all leading environment variable assignments to find the actual binary.
    """
    for tok in command.strip().split():
        if "=" in tok and tok.split("=", 1)[0].replace("_", "").isalnum():
            continue
        return "/" in tok or tok.startswith("./") or tok.startswith("../")
    return False


def _extract_target_hosts(command: str) -> list[str]:
    """Extract ALL target hosts from a curl/wget command.

    Parses positional arguments (URLs) rather than matching 'localhost'
    anywhere in the command string (which would match inside headers,
    query params, or comments).
    """
    tokens = _shlex_split(command)
    hosts: list[str] = []
    skip_next = False
    for token in tokens[1:]:  # skip the binary itself
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if token in (
                "-X",
                "--request",
                "-o",
                "--output",
                "-H",
                "--header",
                "-u",
                "--user",
                "-A",
                "--user-agent",
                "-e",
                "--referer",
            ):
                skip_next = True
                continue
            if token == "--url":
                skip_next = False
                continue
            continue
        m = _URL_HOST_RE.search(token)
        if m:
            hosts.append(m.group(1).lower())
    return hosts


def _has_proxy_env(command: str) -> bool:
    """Check if command has leading proxy environment variable assignments."""
    for tok in command.strip().split():
        if "=" not in tok:
            break
        var_name = tok.split("=", 1)[0].lower()
        if var_name in _PROXY_ENV_VARS:
            return True
    return False


def _unwrap_transparent(command: str, binary: str) -> str | None:
    """If command starts with a transparent wrapper, return the inner command.

    Returns None if there is no inner command (bare wrapper like ``env``).
    """
    parts = _shlex_split(command)
    i = 1
    while i < len(parts):
        tok = parts[i]
        if tok == "--":
            i += 1
            break
        if tok.startswith("-"):
            i += 1
            # Short flags with separate value arg (nice -n 5, stdbuf -o L)
            if len(tok) == 2 and i < len(parts) and not parts[i].startswith("-"):
                i += 1
            continue
        if "=" in tok and binary == "env":
            i += 1
            continue
        # Skip numeric tokens — flag values (nice -n 5) or positional
        # args like timeout duration (timeout 30).
        try:
            float(tok)
            i += 1
            continue
        except ValueError:
            pass
        break

    if i < len(parts):
        return " ".join(parts[i:])
    return None


def _get_compose_subcommand(command: str) -> str | None:
    """Extract the sub-subcommand after 'docker compose'."""
    parts = _shlex_split(command)
    for i, p in enumerate(parts):
        if p == "compose" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _collect_risk_factors(result: dict[str, Any]) -> set[str]:
    """Collect all risk_factors from top-level and sub_commands."""
    factors: set[str] = set(result.get("risk_factors", []))
    for sub in result.get("sub_commands", []):
        factors.update(sub.get("risk_factors", []))
    return factors


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


def classify_shell(command: str) -> tuple[bool, bool]:
    """Classify a shell command as (reversible, contained).

    Phase 1 — sh-guard AST: injection risks, pipeline taint, compound
    decomposition.
    Phase 2 — tool-table chain: each sub-command classified individually,
    worst case wins.
    """
    if not command or not command.strip():
        return _OBSERVE

    # Phase 1: sh-guard AST analysis
    try:
        result = sh_guard_classify(command)
    except Exception:
        log.warning("sh_guard_classify_error", command=command[:80])
        return _BLOCKED

    if _collect_risk_factors(result) & _INJECTION_RISKS:
        return _BLOCKED

    pipeline = result.get("pipeline_flow")
    if pipeline:
        for taint in pipeline.get("taint_flows", []):
            sink_type = taint.get("sink", {}).get("type")
            if sink_type in ("execution", "network_send"):
                return _BLOCKED

    # Phase 2: classify each sub-command via tool tables, worst case wins
    sub_cmds = result.get("sub_commands", [])
    if len(sub_cmds) > 1:
        results = [_classify_single(sub["command"]) for sub in sub_cmds]
        if not results:
            return _OBSERVE
        return (
            all(r for r, _ in results),
            all(c for _, c in results),
        )

    return _classify_single(command)


# ═══════════════════════════════════════════════════════════════════════════
# Classifier chain — each returns a result or None (= pass to next)
# ═══════════════════════════════════════════════════════════════════════════


def _classify_single(command: str) -> tuple[bool, bool]:
    """Classify a single (non-compound) shell command via classifier chain."""
    binary, subcmd = _extract_binary_and_sub(command)
    is_path = _is_path_qualified(command)

    # Pre-checks that short-circuit before the main chain
    if binary in _TRANSPARENT_WRAPPERS:
        inner = _unwrap_transparent(command, binary)
        if inner is not None:
            return _classify_single(inner)
        return _OBSERVE  # bare wrapper (e.g. `env` alone = print env)

    if _DEV_TCP_RE.search(command):
        return _BLOCKED

    if _has_proxy_env(command):
        return _BLOCKED

    if not binary:
        return _OBSERVE

    # Main classifier chain — first match wins
    for classifier in _CLASSIFIER_CHAIN:
        result = classifier(command, binary, subcmd, is_path)
        if result is not None:
            return result

    return _IRREVERSIBLE  # unknown command → conservative default


# ── Individual classifiers ────────────────────────────────────────────────


def _classify_cross_platform_tool(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """git, npm, docker, pip, uv, cargo, etc."""
    table = _CROSS_PLATFORM_TOOLS.get(binary)
    if table is None:
        return None

    # Flag overrides — checked before table lookup
    if binary == "git":
        if _GIT_RESET_HARD_RE.search(command):
            return _IRREVERSIBLE
        if _GIT_PUSH_FORCE_RE.search(command):
            return _BLOCKED

    if binary == "docker":
        if subcmd in ("run", "exec") and _DOCKER_ESCAPE_RE.search(command):
            return _BLOCKED
        if subcmd == "compose" and _get_compose_subcommand(command) in ("exec", "run"):
            return _BLOCKED

    if binary in ("pip", "pip3") and subcmd == "install":
        if _PIP_REMOTE_RE.search(command):
            return _BLOCKED

    # Table lookup
    if subcmd:
        result = table.get(subcmd)
        if result is not None:
            if is_path and result == _OBSERVE:
                return _IRREVERSIBLE  # path-qualified binary → don't trust observe
            return result

    return _IRREVERSIBLE  # unknown subcommand → conservative


def _classify_powershell(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """PowerShell Verb-Noun cmdlets."""
    m = _PS_CMDLET_RE.match(binary)
    if not m:
        return None
    verb = m.group(1).title()
    if verb in _PS_OBSERVE_VERBS:
        return _OBSERVE
    if verb in _PS_UNCONTAINED_VERBS:
        return _BLOCKED
    if verb in _PS_MUTATING_VERBS:
        return _IRREVERSIBLE
    return _IRREVERSIBLE


def _classify_posix(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """POSIX builtins: observe, uncontained, irreversible, conditionally-safe."""
    if binary in _POSIX_OBSERVE:
        return _IRREVERSIBLE if is_path else _OBSERVE

    if binary in _POSIX_TEE:
        return _IRREVERSIBLE

    if binary in _POSIX_UNCONTAINED:
        hosts = _extract_target_hosts(command)
        all_localhost = hosts and all(_LOCALHOST_RE.fullmatch(h) for h in hosts)
        is_mutating = bool(_CURL_MUTATING_RE.search(command))
        if all_localhost:
            return _IRREVERSIBLE if is_mutating else _OBSERVE
        return _BLOCKED if is_mutating else _UNCONTAINED

    if binary in _POSIX_IRREVERSIBLE:
        return _IRREVERSIBLE

    if binary in _POSIX_CONDITIONALLY_SAFE:
        if binary == "find" and _FIND_DANGEROUS_RE.search(command):
            return _IRREVERSIBLE
        if binary == "sort" and _SORT_OUTPUT_RE.search(command):
            return _IRREVERSIBLE
        return _OBSERVE

    return None


def _classify_test_runner(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """Standalone test runners and test subcommands."""
    if binary in _TEST_RUNNERS:
        return _OBSERVE
    if binary in _TEST_SUBCOMMAND_BINARIES and subcmd == "test":
        return _OBSERVE
    return None


def _classify_cmd_exe(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """Windows cmd.exe builtins."""
    if binary in _CMD_OBSERVE:
        return _OBSERVE
    if binary in _CMD_IRREVERSIBLE:
        return _IRREVERSIBLE
    return None


def _classify_interpreter(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """Turing-complete interpreters and code-execution primitives."""
    if binary in _INTERPRETERS or binary in _CODE_EXEC_PRIMITIVES:
        return _BLOCKED
    return None


def _classify_build_tool(
    command: str,
    binary: str,
    subcmd: str | None,
    is_path: bool,
) -> _Result:
    """Build tools that execute arbitrary recipes with full shell + network."""
    if binary in _BUILD_TOOLS:
        return _BLOCKED
    return None


#: Ordered chain of classifiers. First non-None result wins.
_CLASSIFIER_CHAIN = [
    _classify_cross_platform_tool,
    _classify_powershell,
    _classify_posix,
    _classify_test_runner,
    _classify_cmd_exe,
    _classify_interpreter,
    _classify_build_tool,
]
