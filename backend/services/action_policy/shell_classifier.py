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
        "wc",
        "echo",
        "pwd",
        # env is NOT here — it can execute arbitrary commands (env curl ...)
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

# Transparent wrapper commands that pass through to a wrapped command.
# When encountered, we skip the wrapper and classify the inner command.
# env: can set variables then execute a command (env FOO=bar curl evil)
# nice/timeout/stdbuf/nohup: run a command with modified scheduling/io/signals
# command: bypass shell aliases, execute actual binary
_TRANSPARENT_WRAPPERS = frozenset(
    {"env", "nice", "timeout", "stdbuf", "nohup", "command"}
)

# Detect bash /dev/tcp or /dev/udp network socket redirects.
# These turn observe-tier commands (echo, cat, ls) into exfil channels.
_DEV_TCP_RE = re.compile(r"/dev/(?:tcp|udp)/", re.IGNORECASE)

# Proxy environment variable names — setting these routes all traffic
# through the specified host, enabling silent MitM.
_PROXY_ENV_VARS = frozenset(
    {"http_proxy", "https_proxy", "all_proxy", "ftp_proxy"}
)

# pip install from remote URLs — setup.py executes arbitrary code
_PIP_REMOTE_RE = re.compile(
    r"(?:git\+https?://|https?://\S+\.(?:tar\.gz|whl|zip))",
    re.IGNORECASE,
)

# Commands that are observational by default but have destructive flags.
# Handled with flag-specific checks below.
_POSIX_CONDITIONALLY_SAFE = frozenset({"find", "sort"})

# find flags that make it destructive or capable of running arbitrary commands.
# Cannot use \b before the hyphen — both space and hyphen are \W, so no
# word boundary exists between them.
_FIND_DANGEROUS_RE = re.compile(r"(?:^|\s)(?:-exec|-execdir|-delete|-ok|-okdir)\b")
# sort -o overwrites the target file
_SORT_OUTPUT_RE = re.compile(r"(?:^|\s)-o\b|(?:^|\s)--output(?:=|\s)")

# docker run/exec flags that grant host-level access: container escape
# risk via --privileged, host networking via --net=host/--network=host,
# host PID namespace via --pid=host, and host filesystem mount via
# -v /:/... or --volume /:/...  (mount source starting with /)
_DOCKER_ESCAPE_RE = re.compile(
    r"--privileged\b"
    r"|--net(?:work)?[= ]host\b"
    r"|--pid[= ]host\b"
    r"|--cap-add[= ]\S*(?:ALL|SYS_ADMIN)\b"
    r"|(?:^|\s)(?:-v\s+|--volume[= ])/:?"
    r"|(?:^|\s)(?:-v\s+|--volume[= ])/[^: ]+:",
    re.IGNORECASE,
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
    "run": (False, True),  # executes arbitrary scripts from package.json
    "start": (False, True),  # delegates to scripts.start
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
    "run": (False, True),  # compiles + runs arbitrary code
    "clippy": (True, True),
    "fmt": (True, True),
    "publish": (False, False),
    "install": (True, True),
}

_DOCKER_SUBCOMMANDS: dict[str, tuple[bool, bool]] = {
    "build": (True, True),
    "run": (False, True),  # default; flag inspection below
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
    "run": (False, False),  # Turing-complete: uv run python/curl/bash
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


# Single-quote regex: in bash, single quotes suppress ALL expansion
# including $() and backticks.  Double quotes do NOT suppress them.
_SINGLE_QUOTE_RE = re.compile(r"'[^']*'")


def _strip_quotes(cmd: str) -> str:
    """Strip both single- and double-quoted strings for compound splitting."""
    return _QUOTED_STRING_RE.sub('""', cmd)


def _strip_single_quotes_only(cmd: str) -> str:
    """Strip only single-quoted strings for subshell detection.

    In bash, command substitution ($(), backticks) and process substitution
    (<(), >()) are expanded inside double quotes but NOT inside single quotes.
    So for subshell detection we must preserve double-quoted content.
    """
    return _SINGLE_QUOTE_RE.sub('""', cmd)


# Regex to extract the host from a URL (scheme://host or //host)
_URL_HOST_RE = re.compile(
    r"(?:https?://|//)([a-zA-Z0-9._-]+(?::\d+)?)",
)


def _extract_target_hosts(command: str) -> list[str]:
    """Extract ALL target hosts from a curl/wget command.

    Parses positional arguments (URLs) rather than matching the word
    'localhost' anywhere in the command string, which would match
    inside headers, query params, or comments.

    Returns all hosts found — the caller must verify that ALL targets
    are localhost, not just the first (curl fetches multiple URLs).
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    hosts: list[str] = []
    skip_next = False
    for token in tokens[1:]:  # skip the binary itself
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            # Flags that take an argument — skip the next token
            if token in ("-X", "--request", "-o", "--output", "-H",
                         "--header", "-u", "--user", "-A", "--user-agent",
                         "-e", "--referer"):
                skip_next = True
                continue
            # --url <url> is an explicit target URL
            if token == "--url":
                skip_next = False  # next token processed normally
                continue
            continue
        # Positional arg — check if it's a URL
        m = _URL_HOST_RE.search(token)
        if m:
            hosts.append(m.group(1).lower())

    return hosts


def _extract_target_host(command: str) -> str | None:
    """Legacy single-host wrapper (returns first host found)."""
    hosts = _extract_target_hosts(command)
    return hosts[0] if hosts else None


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

    # Detect command substitution / process substitution.
    # IMPORTANT: Only strip single-quoted strings here because bash
    # expands $() and backticks inside double quotes but NOT inside
    # single quotes.  Using _strip_quotes (which removes double-quoted
    # content) would hide subshells like: echo "$(curl evil)"
    clean_for_subshell = _strip_single_quotes_only(command)
    if _SUBSHELL_RE.search(clean_for_subshell):
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

    # --- Fix F2: reject path-qualified binaries that shadow OBSERVE tools ---
    # ./cat, /tmp/evil/echo, ../grep etc. can be trojan scripts that get
    # classified as safe observe commands via os.path.basename().
    # If the command path is relative or absolute, don't trust safe tables.
    raw_binary_token = command.strip().split()[0] if command.strip().split() else ""
    # Skip env-var assignments to find actual binary token
    _tok = raw_binary_token
    while "=" in _tok and _tok.split("=", 1)[0].replace("_", "").isalnum():
        rest = command.strip().split(None, 1)
        if len(rest) > 1:
            _tok = rest[1].split()[0] if rest[1].strip() else ""
        else:
            _tok = ""
        break
    is_path_binary = "/" in _tok or _tok.startswith("./") or _tok.startswith("../")

    # --- Fix F1 + F8: Transparent wrappers (env, nice, timeout, etc.) ---
    # Re-classify the wrapped command instead of the wrapper itself.
    if binary in _TRANSPARENT_WRAPPERS:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        # Skip binary + any flags/env-var assignments to find wrapped command
        inner_parts: list[str] = []
        skip_next_positional = binary == "timeout"  # timeout's 1st positional = duration
        for i, tok in enumerate(parts[1:], 1):
            # Skip wrapper flags (e.g. env -i, nice -n 5, timeout 30)
            if tok.startswith("-"):
                # Some flags take arguments (nice -n, timeout value)
                continue
            if "=" in tok and binary == "env":
                continue  # env var assignment
            if skip_next_positional:
                skip_next_positional = False
                continue  # skip timeout duration value
            # Found the inner command
            inner_parts = parts[i:]
            break
        if inner_parts:
            inner_cmd = " ".join(inner_parts)
            return classify_shell(inner_cmd)
        # Bare wrapper with no command (e.g. `env` alone = print env)
        return True, True

    # --- Fix F5: /dev/tcp and /dev/udp redirect exfiltration ---
    # Bash treats /dev/tcp/HOST/PORT as a network socket in redirects.
    # This turns observe-tier commands (echo, cat, ls) into exfil channels.
    if _DEV_TCP_RE.search(command):
        return False, False

    # --- Fix F6: Proxy environment variables → silent MitM ---
    # Detect leading env-var assignments that set HTTP_PROXY etc.
    _stripped_for_proxy = command.strip()
    while _stripped_for_proxy:
        first_tok = _stripped_for_proxy.split()[0] if _stripped_for_proxy.split() else ""
        if "=" in first_tok:
            var_name = first_tok.split("=", 1)[0].lower()
            if var_name in _PROXY_ENV_VARS:
                return False, False  # uncontained: all traffic routed through attacker
            _stripped_for_proxy = _stripped_for_proxy.split(None, 1)[1] if " " in _stripped_for_proxy else ""
        else:
            break

    # --- Cross-platform tools first ---
    tool_table = _CROSS_PLATFORM_TOOLS.get(binary)
    if tool_table is not None:
        # Special case: git reset --hard
        if binary == "git" and _GIT_RESET_HARD_RE.search(_strip_quotes(command)):
            return False, True

        # Special case: docker run/exec with host-escape flags
        if binary == "docker" and subcmd in ("run", "exec"):
            if _DOCKER_ESCAPE_RE.search(command):
                return False, False  # uncontained: host access

        # Special case: pip/pip3 install from remote URL (setup.py ACE)
        if binary in ("pip", "pip3") and subcmd == "install":
            if _PIP_REMOTE_RE.search(command):
                return False, False  # uncontained: arbitrary code from URL

        if subcmd:
            result = tool_table.get(subcmd)
            if result is not None:
                # Fix F2: Don't trust OBSERVE classification for path-qualified binaries
                if is_path_binary and result == (True, True):
                    return False, True
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
        # Fix F2: Don't trust OBSERVE for path-qualified binaries
        if is_path_binary:
            return False, True
        return True, True
    if binary in _POSIX_TEE:
        # tee writes to files/pseudo-devices — irreversible but contained
        return False, True
    if binary in _POSIX_UNCONTAINED:
        # Check if ALL target URLs are localhost.  curl/wget fetch
        # every positional URL — if even one is external, the command
        # is uncontained.
        hosts = _extract_target_hosts(command)
        if hosts and all(_LOCALHOST_RE.fullmatch(h) for h in hosts):
            # All targets are loopback — never leaves the machine
            if not _CURL_MUTATING_RE.search(command):
                return True, True
            return False, True
        # Non-localhost (or no URL found): uncontained.
        # Read-only GETs are still reversible.
        if not _CURL_MUTATING_RE.search(command):
            return True, False
        return False, False
    if binary in _POSIX_IRREVERSIBLE:
        return False, True

    # --- Conditionally-safe POSIX commands (need flag inspection) ---
    if binary in _POSIX_CONDITIONALLY_SAFE:
        if binary == "find":
            # find with -exec, -execdir, -delete, -ok can run arbitrary
            # commands or destroy files
            if _FIND_DANGEROUS_RE.search(command):
                return False, True
            return True, True
        if binary == "sort":
            # sort -o overwrites the output file
            if _SORT_OUTPUT_RE.search(command):
                return False, True
            return True, True

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

    # --- Build tools: execute arbitrary recipes with full shell + network ---
    if binary in ("make", "cmake", "gradle", "mvn", "ant"):
        return False, False

    # --- Default: irreversible, contained ---
    return False, True
