"""Shell command classifier — POSIX, PowerShell, cmd.exe, and cross-platform tools.

Parses a shell command string and returns (reversible, contained) booleans.
"""

from __future__ import annotations

import re
import shlex


# ---------------------------------------------------------------------------
# POSIX builtins
# ---------------------------------------------------------------------------

_POSIX_OBSERVE = frozenset({
    "ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg",
    "find", "wc", "echo", "pwd", "env", "printenv", "whoami", "date",
    "file", "stat", "du", "tree", "sort", "diff", "more", "less",
    "which", "type", "basename", "dirname", "realpath", "readlink",
    "test", "true", "false", "tee",
})

_POSIX_UNCONTAINED = frozenset({
    "curl", "wget", "ssh", "scp", "rsync", "nc", "ncat",
    "telnet", "ftp", "sftp", "sendmail", "mail",
})

_POSIX_IRREVERSIBLE = frozenset({
    "rm", "shred", "dd", "mkfs", "fdisk",
    "kill", "killall", "pkill", "shutdown", "reboot", "halt",
})


# ---------------------------------------------------------------------------
# PowerShell verb taxonomy
# ---------------------------------------------------------------------------

_PS_OBSERVE_VERBS = frozenset({
    "Get", "Find", "Search", "Test", "Measure",
    "Compare", "Select", "Format", "Out", "Show", "Read", "Watch",
    "Write",
})

_PS_MUTATING_VERBS = frozenset({
    "Set", "New", "Add", "Remove", "Clear",
    "Move", "Rename", "Copy", "Update", "Reset", "Enable", "Disable",
})

_PS_UNCONTAINED_VERBS = frozenset({
    "Send", "Connect", "Disconnect", "Publish", "Push", "Invoke-Web",
})


# ---------------------------------------------------------------------------
# cmd.exe builtins
# ---------------------------------------------------------------------------

_CMD_OBSERVE = frozenset({
    "dir", "type", "echo", "set", "ver", "where",
    "findstr", "find", "more", "tree", "path", "vol",
})

_CMD_IRREVERSIBLE = frozenset({
    "del", "erase", "rmdir", "rd", "format",
})


# ---------------------------------------------------------------------------
# Cross-platform tool subcommand tables
# ---------------------------------------------------------------------------

_GIT_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "status":       (True,  True),
    "log":          (True,  True),
    "diff":         (True,  True),
    "show":         (True,  True),
    "branch":       (True,  True),
    "stash":        (True,  True),
    "add":          (True,  True),
    "commit":       (True,  True),
    "checkout":     (True,  True),
    "switch":       (True,  True),
    "restore":      (True,  True),
    "revert":       (True,  True),
    "tag":          (True,  True),
    "fetch":        (True,  False),
    "pull":         (True,  False),
    "push":         (True,  False),
    "force-push":   (False, False),
    "reset":        (True,  True),   # default; --hard overridden below
    "clean":        (False, True),
    "clone":        (True,  False),
    "remote":       (True,  True),
    "merge":        (True,  True),
    "rebase":       (True,  True),
    "cherry-pick":  (True,  True),
}

_NPM_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install":  (True,  True),
    "ci":       (True,  True),
    "test":     (True,  True),
    "run":      (True,  True),
    "start":    (True,  True),
    "build":    (True,  True),
    "publish":  (False, False),
    "unpublish": (False, False),
    "link":     (True,  True),
    "uninstall": (True, True),
}

_CARGO_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build":    (True,  True),
    "test":     (True,  True),
    "check":    (True,  True),
    "run":      (True,  True),
    "clippy":   (True,  True),
    "fmt":      (True,  True),
    "publish":  (False, False),
    "install":  (True,  True),
}

_DOCKER_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build":    (True,  True),
    "run":      (True,  True),
    "exec":     (False, True),
    "ps":       (True,  True),
    "images":   (True,  True),
    "logs":     (True,  True),
    "pull":     (True,  False),
    "push":     (False, False),
    "rm":       (True,  True),
    "rmi":      (True,  True),
    "stop":     (True,  True),
    "start":    (True,  True),
    "compose":  (True,  True),
}

_PIP_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install":  (True,  True),
    "uninstall": (True, True),
    "list":     (True,  True),
    "show":     (True,  True),
    "freeze":   (True,  True),
}

_UV_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "sync":     (True,  True),
    "add":      (True,  True),
    "remove":   (True,  True),
    "run":      (True,  True),
    "lock":     (True,  True),
    "pip":      (True,  True),
    "publish":  (False, False),
}

_CROSS_PLATFORM_TOOLS: dict[str, dict[str, tuple[bool, bool]]] = {
    "git": _GIT_SUBCOMMANDS,
    "npm": _NPM_SUBCOMMANDS,
    "npx": {k: v for k, v in _NPM_SUBCOMMANDS.items()},
    "yarn": _NPM_SUBCOMMANDS,
    "pnpm": _NPM_SUBCOMMANDS,
    "cargo": _CARGO_SUBCOMMANDS,
    "docker": _DOCKER_SUBCOMMANDS,
    "pip": _PIP_SUBCOMMANDS,
    "pip3": _PIP_SUBCOMMANDS,
    "uv": _UV_SUBCOMMANDS,
}

# Regex to detect git reset --hard
_GIT_RESET_HARD_RE = re.compile(r"\bgit\s+reset\b[^|;&\n]*?\s--hard\b", re.IGNORECASE)
_QUOTED_STRING_RE = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'', re.DOTALL)

# PowerShell cmdlet pattern: Verb-Noun
_PS_CMDLET_RE = re.compile(r"^([A-Z][a-z]+)-", re.IGNORECASE)


def _strip_quotes(cmd: str) -> str:
    return _QUOTED_STRING_RE.sub('""', cmd)


def _extract_binary_and_sub(cmd: str) -> tuple[str, str | None]:
    """Extract the binary name and first subcommand from a command string."""
    stripped = cmd.strip()
    # Skip leading environment variable assignments (FOO=bar cmd ...)
    while "=" in stripped.split()[0] if stripped.split() else False:
        stripped = stripped.split(None, 1)[1] if " " in stripped else ""

    try:
        parts = shlex.split(stripped)
    except ValueError:
        parts = stripped.split()

    if not parts:
        return "", None

    import os
    binary = os.path.basename(parts[0]).lower()

    # Strip common suffixes
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".sh"):
        if binary.endswith(suffix):
            binary = binary[: -len(suffix)]

    subcmd = parts[1] if len(parts) > 1 and not parts[1].startswith("-") else None
    return binary, subcmd


def classify_shell(command: str) -> tuple[bool, bool]:
    """Classify a shell command as (reversible, contained).

    Returns conservative defaults (False, True) for unknown commands —
    irreversible but contained.
    """
    if not command or not command.strip():
        return True, True

    # Handle compound commands: classify each part, return the worst case
    # Split on &&, ||, ; but not inside quotes
    clean = _strip_quotes(command)
    parts = re.split(r"\s*(?:&&|\|\||;)\s*", clean)
    if len(parts) > 1:
        results = [classify_shell(p) for p in parts if p.strip()]
        if not results:
            return True, True
        reversible = all(r for r, _ in results)
        contained = all(c for _, c in results)
        return reversible, contained

    # Single command
    binary, subcmd = _extract_binary_and_sub(command)
    if not binary:
        return True, True

    # --- Cross-platform tools first ---
    tool_table = _CROSS_PLATFORM_TOOLS.get(binary)
    if tool_table is not None:
        # Special case: git reset --hard
        if binary == "git" and _GIT_RESET_HARD_RE.search(_strip_quotes(command)):
            return False, True

        if subcmd:
            result = tool_table.get(subcmd)
            if result is not None:
                return result
        # Unknown subcommand for known tool: conservative
        return False, True

    # --- PowerShell cmdlets ---
    ps_match = _PS_CMDLET_RE.match(binary)
    if ps_match:
        verb = ps_match.group(1).title()
        if verb in _PS_OBSERVE_VERBS:
            return True, True
        if verb in _PS_UNCONTAINED_VERBS:
            return False, False
        if verb in _PS_MUTATING_VERBS:
            return False, True
        return False, True

    # Also check if the full first token is a PS cmdlet (e.g. Get-ChildItem)
    first_token = command.strip().split()[0] if command.strip().split() else ""
    ps_match2 = _PS_CMDLET_RE.match(first_token)
    if ps_match2:
        verb = ps_match2.group(1).title()
        if verb in _PS_OBSERVE_VERBS:
            return True, True
        if verb in _PS_UNCONTAINED_VERBS:
            return False, False
        if verb in _PS_MUTATING_VERBS:
            return False, True

    # --- POSIX ---
    if binary in _POSIX_OBSERVE:
        return True, True
    if binary in _POSIX_UNCONTAINED:
        return False, False
    if binary in _POSIX_IRREVERSIBLE:
        return False, True

    # --- cmd.exe ---
    if binary in _CMD_OBSERVE:
        return True, True
    if binary in _CMD_IRREVERSIBLE:
        return False, True

    # --- Python/Node/Ruby interpreters: contained but irreversible ---
    if binary in ("python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"):
        return False, True

    # --- Default: irreversible, contained ---
    return False, True
