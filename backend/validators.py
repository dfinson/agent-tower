"""Shared validation patterns used across the codebase."""

from __future__ import annotations

import re

# Git ref validation: branches, tags, and base refs
REF_PATTERN = re.compile(r"^[a-zA-Z0-9/_.-]+$")

# Branch naming convention: type/slug
BRANCH_RE = re.compile(r"^(feat|fix|chore|docs|test)/[a-z0-9][a-z0-9-]{0,43}$")

# Worktree directory naming
WORKTREE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")
