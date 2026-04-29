"""Shared helpers for evaluation tools."""

from __future__ import annotations


def extract_file_identifiers(files: list[str]) -> set[str]:
    """Extract searchable identifiers from file paths — full path, basename, and stem."""
    ids: set[str] = set()
    for f in files:
        if not f:
            continue
        ids.add(f)
        if "/" in f:
            ids.add(f.rsplit("/", 1)[-1])
        stem = f.split("/")[-1].split(".")[0]
        if stem:
            ids.add(stem)
    return ids
