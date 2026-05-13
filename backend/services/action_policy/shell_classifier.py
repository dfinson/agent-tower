"""Shell command classifier — POSIX, PowerShell, cmd.exe, and cross-platform tools.

Parses a shell command string and returns (reversible, contained) booleans.
"""

from __future__ import annotations

import os
import re
import shlex

# ---------------------------------------------------------------------------
# POSIX builtins
# ---------------------------------------------------------------------------

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
        "find",
        "wc",
        "echo",
        "pwd",
        "env",
        "printenv",
        "whoami",
        "date",
        "file",
        "stat",
        "du",
        "tree",
        "sort",
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

# tee: can write to arbitrary paths including pseudo-devices (/dev/tcp);
# classified as irreversible + contained, not observe.
_POSIX_TEE = frozenset({"tee"})

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


# ---------------------------------------------------------------------------
# PowerShell verb taxonomy
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# cmd.exe builtins
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Cross-platform tool subcommand tables
# ---------------------------------------------------------------------------

_GIT_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "status": (True, True),
    "log": (True, True),
    "diff": (True, True),
    "show": (True, True),
    "branch": (True, True),
    "stash": (True, True),
    "add": (True, True),
    "commit": (True, True),
    "checkout": (True, True),
    "switch": (True, True),
    "restore": (True, True),
    "revert": (True, True),
    "tag": (True, True),
    "fetch": (True, False),
    "pull": (True, False),
    "push": (True, False),
    "force-push": (False, False),
    "reset": (True, True),  # default; --hard overridden below
    "clean": (False, True),
    "clone": (True, False),
    "remote": (True, True),
    "merge": (True, True),
    "rebase": (True, True),
    "cherry-pick": (True, True),
}

_NPM_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install": (True, True),
    "ci": (True, True),
    "test": (True, True),
    "run": (True, True),
    "start": (True, True),
    "build": (True, True),
    "publish": (False, False),
    "unpublish": (False, False),
    "link": (True, True),
    "uninstall": (True, True),
}

_CARGO_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build": (True, True),
    "test": (True, True),
    "check": (True, True),
    "run": (True, True),
    "clippy": (True, True),
    "fmt": (True, True),
    "publish": (False, False),
    "install": (True, True),
}

_DOCKER_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build": (True, True),
    "run": (True, True),
    "exec": (False, True),
    "ps": (True, True),
    "images": (True, True),
    "logs": (True, True),
    "pull": (True, False),
    "push": (False, False),
    "rm": (True, True),
    "rmi": (True, True),
    "stop": (True, True),
    "start": (True, True),
    "compose": (True, True),
}

_PIP_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "install": (True, True),
    "uninstall": (True, True),
    "list": (True, True),
    "show": (True, True),
    "freeze": (True, True),
}

_UV_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "sync": (True, True),
    "add": (True, True),
    "remove": (True, True),
    "run": (True, True),
    "lock": (True, True),
    "pip": (True, True),
    "publish": (False, False),
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

# Localhost detection — loopback traffic never leaves the machine
_LOCALHOST_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|::1|\[::1\]|0\.0\.0\.0)"
    r"(?::\d+)?",  # optional port
    re.IGNORECASE,
)

# Command/process substitution patterns — these can execute arbitrary
# commands invisibly inside an otherwise-safe outer command.
_SUBSHELL_RE = re.compile(
    r"\$\("         # $(...)
    r"|`"           # backtick substitution
    r"|<\("         # process substitution <(...)
    r"|>\(",        # process substitution >(...)
)

# Mutating HTTP method flags for curl/wget
_CURL_MUTATING_RE = re.compile(
    r"""
    -X\s*(?:POST|PUT|DELETE|PATCH)  # explicit method
    | --request\s+(?:POST|PUT|DELETE|PATCH)
    | --data(?:-\w+)?\b             # -d / --data / --data-raw / --data-binary
    | -d\s                          # short -d flag
    | --upload-file\b
    | -T\s                          # upload shorthand
    | -F\s                          # form upload
    | --form\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Test runners — local process execution with no external side effects
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

# Binaries that are test runners when invoked with a "test" subcommand
# (handled in _CROSS_PLATFORM_TOOLS already for cargo/npm/etc.
# This covers: `go test`, `dotnet test`, `swift test`, `mix test`)
_TEST_SUBCOMMAND_BINARIES = frozenset(
    {
        "go",
        "dotnet",
        "swift",
        "mix",
        "elixir",
    }
)


def _strip_quotes(cmd: str) -> str:
    return _QUOTED_STRING_RE.sub('""', cmd)


# Regex to extract the host from a URL (scheme://host or //host)
_URL_HOST_RE = re.compile(
    r"(?:https?://|//)([a-zA-Z0-9._-]+(?::\d+)?)",
)


def _extract_target_host(command: str) -> str | None:
    """Extract the target host from a curl/wget command.

    Parses positional arguments (URLs) rather than matching the word
    'localhost' anywhere in the command string, which would match
    inside headers, query params, or comments.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    # Find URL-like positional args (not flags)
    skip_next = False
    for token in tokens[1:]:  # skip the binary itself
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            # Flags that take an argument — skip the next token
            if token in ("-X", "--request", "-o", "--output", "-H",
                         "--header", "-u", "--user", "-A", "--user-agent",
                         "-e", "--referer", "--url"):
                if token == "--url":
                    # --url <url> is the explicit target
                    skip_next = False  # handled below
                else:
                    skip_next = True
                continue
            continue
        # Looks like a positional arg — check if it's a URL
        m = _URL_HOST_RE.search(token)
        if m:
            return m.group(1).lower()

    return None


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
    # Split on &&, ||, ;, | (pipes), and \n (shell line separator)
    # but not inside quotes.
    clean = _strip_quotes(command)

    # Detect command substitution / process substitution in the cleaned
    # command (after quote removal).  These can execute arbitrary
    # commands invisibly inside an otherwise-safe outer command.
    # Conservative: (False, False) — irreversible and uncontained.
    if _SUBSHELL_RE.search(clean):
        return False, False

    parts = re.split(r"\s*(?:&&|\|\||;|\||\n)\s*", clean)
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
    if binary in _POSIX_TEE:
        # tee writes to files/pseudo-devices — irreversible but contained
        return False, True
    if binary in _POSIX_UNCONTAINED:
        # Check if the *target URL* is localhost, not just if "localhost"
        # appears anywhere in the command (headers, comments, etc.)
        target_host = _extract_target_host(command)
        if target_host and _LOCALHOST_RE.fullmatch(target_host):
            # Loopback never leaves the machine
            if not _CURL_MUTATING_RE.search(command):
                return True, True
            return False, True
        # Non-localhost: uncontained.  Read-only GETs are still reversible.
        if not _CURL_MUTATING_RE.search(command):
            return True, False
        return False, False
    if binary in _POSIX_IRREVERSIBLE:
        return False, True

    # --- Test runners (standalone binaries) ---
    if binary in _TEST_RUNNERS:
        return True, True

    # --- Test subcommand binaries (e.g. `go test`, `dotnet test`) ---
    if binary in _TEST_SUBCOMMAND_BINARIES and subcmd == "test":
        return True, True

    # --- cmd.exe ---
    if binary in _CMD_OBSERVE:
        return True, True
    if binary in _CMD_IRREVERSIBLE:
        return False, True

    # --- Python/Node/Ruby interpreters: uncontained — Turing-complete,
    # can perform arbitrary network I/O via standard library ---
    if binary in ("python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"):
        return False, False

    # --- Default: irreversible, contained ---
    return False, True
