"""Dependency descriptors for setup/preflight checks.

Defines the external tool requirements (Git, Node, npm, etc.) and their
platform-specific install instructions.  Extracted from setup_checks.py
to separate data from orchestration logic.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field

HOST_PLATFORM = platform.system().lower()  # "linux", "darwin", "windows"


@dataclass
class Dependency:
    name: str
    command: str
    install_instructions: dict[str, str]
    url: str
    required: bool = True
    auto_install_cmd: dict[str, list[str]] = field(default_factory=dict)


DEPENDENCIES: list[Dependency] = [
    Dependency(
        name="Git",
        command="git",
        url="https://git-scm.com/downloads",
        required=True,
        install_instructions={
            "linux": "sudo apt-get install -y git",
            "darwin": "brew install git",
            "windows": "Download from https://git-scm.com/downloads",
        },
        auto_install_cmd={
            "linux": ["sudo", "apt-get", "install", "-y", "git"],
            "darwin": ["brew", "install", "git"],
        },
    ),
    Dependency(
        name="Node.js",
        command="node",
        url="https://nodejs.org/",
        required=True,
        install_instructions={
            "linux": (
                "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs"
            ),
            "darwin": "brew install node",
            "windows": "Download installer from https://nodejs.org/",
        },
        auto_install_cmd={
            "linux": ["sudo", "apt-get", "install", "-y", "nodejs"],
            "darwin": ["brew", "install", "node"],
        },
    ),
    Dependency(
        name="npm",
        command="npm",
        url="https://nodejs.org/",
        required=True,
        install_instructions={
            "linux": "Included with Node.js — reinstall Node if missing",
            "darwin": "Included with Node.js — reinstall Node if missing",
            "windows": "Included with Node.js — reinstall Node if missing",
        },
    ),
    Dependency(
        name="GitHub CLI",
        command="gh",
        url="https://cli.github.com/",
        required=True,
        install_instructions={
            "linux": (
                "sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-key 23F3D4EA75716059\n"
                "sudo apt-add-repository https://cli.github.com/packages\n"
                "sudo apt-get update && sudo apt-get install gh"
            ),
            "darwin": "brew install gh",
            "windows": "winget install --id GitHub.cli",
        },
        auto_install_cmd={
            "linux": ["sudo", "apt-get", "install", "-y", "gh"],
            "darwin": ["brew", "install", "gh"],
        },
    ),
    Dependency(
        name="Dev Tunnels CLI",
        command="devtunnel",
        url="https://aka.ms/devtunnels/cli",
        required=False,
        install_instructions={
            "linux": "Install from https://aka.ms/devtunnels/cli",
            "darwin": "Install from https://aka.ms/devtunnels/cli",
            "windows": "Install from https://aka.ms/devtunnels/cli",
        },
    ),
]
