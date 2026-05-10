"""Review story density, edge-case classification, and aggregation (§11.4-11.7).

This module classifies structural changes by narrative density, detects
edge cases (docs, generated code, bulk renames, vendor files), and groups
changes into aggregation patterns when content exceeds cognitive limits.

The output feeds the review-story endpoint — deterministic section structure
with optional LLM-generated narrative prose for high-density sections.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from typing import TYPE_CHECKING, Any, TypedDict

import structlog

if TYPE_CHECKING:
    from backend.models.api_schemas import StructuralChange

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Density levels (§11.4.1)
# ---------------------------------------------------------------------------


class DensityLevel(str, Enum):
    FULL = "full"
    SUMMARY = "summary"
    GROUPED = "grouped"
    COUNT_ONLY = "count_only"
    OMITTED = "omitted"


# ---------------------------------------------------------------------------
# Edge-case kinds (§11.5)
# ---------------------------------------------------------------------------


class EdgeCaseKind(str, Enum):
    DOCUMENTATION = "documentation"
    GENERATED = "generated"
    BULK_RENAME = "bulk_rename"
    VENDOR = "vendor"
    PURE_DELETION = "pure_deletion"


class EdgeCaseBlock(TypedDict, total=False):
    kind: str
    icon: str
    title: str
    files: list[str]
    detail: str


# ---------------------------------------------------------------------------
# Community rollup (§11.6.1)
# ---------------------------------------------------------------------------


class CommunityRollup(TypedDict, total=False):
    name: str
    change_count: int
    avg_risk: float
    highest_risk_symbol: str | None
    highest_risk: float
    summary: str


# ---------------------------------------------------------------------------
# Pattern grouping (§11.6.2)
# ---------------------------------------------------------------------------


class PatternGroup(TypedDict, total=False):
    pattern: str
    count: int
    files: list[str]
    summary: str


# ---------------------------------------------------------------------------
# File classification patterns
# ---------------------------------------------------------------------------

_DOC_EXTENSIONS = frozenset({
    ".md", ".rst", ".txt", ".adoc", ".asciidoc",
})
_DOC_PATHS = re.compile(r"(^docs?/|/docs?/|README|CHANGELOG|LICENSE|CONTRIBUTING)", re.IGNORECASE)

_GENERATED_PATHS = re.compile(
    r"(alembic/versions/|migrations/|__generated__|\.generated\.|"
    r"schema\.d\.ts$|openapi\.json$|openapi\.yaml$|\.pb\.go$|_pb2\.py$)",
    re.IGNORECASE,
)
_GENERATED_HEADERS = frozenset({
    "# generated", "// generated", "/* generated", "# auto-generated",
    "// auto-generated", "/* auto-generated", "# do not edit",
    "// do not edit", "/* do not edit",
})

_VENDOR_PATHS = re.compile(
    r"(^vendor/|/vendor/|node_modules/|\.lock$|lock\.json$|"
    r"uv\.lock$|poetry\.lock$|yarn\.lock$|pnpm-lock\.yaml$)",
    re.IGNORECASE,
)

_LOCK_FILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "uv.lock", "poetry.lock", "Gemfile.lock", "Cargo.lock",
    "go.sum", "composer.lock",
})

# Cognitive-load budget caps from §11.2.2
_ATTENTION_CAP = 5
_BODY_CAP = 10
_ADDITIVE_CAP = 7


# ---------------------------------------------------------------------------
# Density classification (§11.4)
# ---------------------------------------------------------------------------


def classify_density(
    change: "StructuralChange",
    all_changes: list["StructuralChange"],
) -> DensityLevel:
    """Assign a density level to a single structural change per §11.4."""
    # Escalation rules (§11.4.2): always FULL
    if change.ref_tiers.get("unverified", 0) > 0:
        return DensityLevel.FULL
    if change.ref_count > 10:
        return DensityLevel.FULL if change.category == "breaking" else DensityLevel.SUMMARY
    if change.category == "breaking":
        return DensityLevel.FULL

    # De-escalation rules (§11.4.2)
    if change.category == "additive" and change.ref_count == 0:
        return DensityLevel.COUNT_ONLY
    if change.category == "non-structural":
        return DensityLevel.OMITTED

    # Test mirrors — if it's a test file that mirrors a production change
    if _is_test_file(change.file):
        prod_files = {c.file for c in all_changes if not _is_test_file(c.file)}
        mirrored = _find_production_mirror(change.file, prod_files)
        if mirrored:
            return DensityLevel.OMITTED

    # Mechanical changes (all refs verified, purely internal)
    if (
        change.ref_tiers.get("verified", 0) + change.ref_tiers.get("inferred", 0) == change.ref_count
        and change.ref_count > 0
        and change.risk < 0.3
    ):
        return DensityLevel.SUMMARY

    # Default by category
    if change.category == "body":
        return DensityLevel.SUMMARY
    if change.category == "additive":
        return DensityLevel.SUMMARY

    return DensityLevel.SUMMARY


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file."""
    base = os.path.basename(path).lower()
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or base.endswith(".test.ts")
        or base.endswith(".test.tsx")
        or base.endswith(".spec.ts")
        or base.endswith(".spec.tsx")
        or "/tests/" in path
        or "/test/" in path
        or "/__tests__/" in path
    )


def _find_production_mirror(test_path: str, prod_files: set[str]) -> str | None:
    """Find a production file that this test mirrors."""
    base = os.path.basename(test_path).lower()
    # test_foo.py → foo.py
    for prefix in ("test_",):
        if base.startswith(prefix):
            candidate = base[len(prefix):]
            if any(os.path.basename(f).lower() == candidate for f in prod_files):
                return candidate
    # foo.test.ts → foo.ts
    for suffix in (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"):
        if base.endswith(suffix):
            candidate = base[: -len(suffix)] + base[base.rfind("."):]
            if any(os.path.basename(f).lower() == candidate for f in prod_files):
                return candidate
    return None


# ---------------------------------------------------------------------------
# Edge-case detection (§11.5)
# ---------------------------------------------------------------------------


def detect_edge_cases(
    changes: list["StructuralChange"],
) -> tuple[list[EdgeCaseBlock], list["StructuralChange"]]:
    """Detect and extract edge-case changes, returning blocks + remaining changes.

    Returns:
        (edge_case_blocks, remaining_changes) — the remaining changes are those
        NOT absorbed into an edge-case block.
    """
    edge_blocks: list[EdgeCaseBlock] = []
    remaining: list["StructuralChange"] = []

    doc_files: list[str] = []
    generated_files: list[str] = []
    vendor_files: list[str] = []
    bulk_candidates: list["StructuralChange"] = []

    for ch in changes:
        filepath = ch.file

        # Lock files — always omit (§11.5.4)
        if os.path.basename(filepath) in _LOCK_FILES:
            continue

        # Documentation (§11.5.1)
        _, ext = os.path.splitext(filepath)
        if ext.lower() in _DOC_EXTENSIONS or _DOC_PATHS.search(filepath):
            doc_files.append(filepath)
            continue

        # Generated / migrations (§11.5.2)
        if _GENERATED_PATHS.search(filepath):
            generated_files.append(filepath)
            continue

        # Vendor (§11.5.4)
        if _VENDOR_PATHS.search(filepath):
            vendor_files.append(filepath)
            continue

        remaining.append(ch)
        bulk_candidates.append(ch)

    # Build edge-case blocks
    if doc_files:
        edge_blocks.append(EdgeCaseBlock(
            kind=EdgeCaseKind.DOCUMENTATION.value,
            icon="📄",
            title=f"Documentation ({len(doc_files)} file{'s' if len(doc_files) != 1 else ''})",
            files=doc_files[:10],
            detail="These files have no structural impact. Review for accuracy and completeness outside the structural story.",
        ))

    if generated_files:
        edge_blocks.append(EdgeCaseBlock(
            kind=EdgeCaseKind.GENERATED.value,
            icon="🔧",
            title=f"Generated / Migrations ({len(generated_files)} file{'s' if len(generated_files) != 1 else ''})",
            files=generated_files[:10],
            detail="Generated content. Verify the source (schema/spec), not the output.",
        ))

    if vendor_files:
        edge_blocks.append(EdgeCaseBlock(
            kind=EdgeCaseKind.VENDOR.value,
            icon="📦",
            title=f"Dependencies ({len(vendor_files)} file{'s' if len(vendor_files) != 1 else ''})",
            files=vendor_files[:5],
            detail="Dependency manifests. Verify version constraints are intentional.",
        ))

    # Bulk rename detection (§11.5.3)
    bulk_group = _detect_bulk_rename(bulk_candidates)
    if bulk_group:
        edge_blocks.append(bulk_group)
        # Remove bulk-renamed files from remaining
        bulk_files = set(bulk_group.get("files", []))
        remaining = [c for c in remaining if c.file not in bulk_files]

    # Pure deletions (§11.5.5) — group zero-caller deletions
    deleted = [c for c in remaining if c.kind == "removed" and c.ref_count == 0]
    if len(deleted) >= 3:
        deleted_files = [c.file for c in deleted]
        edge_blocks.append(EdgeCaseBlock(
            kind=EdgeCaseKind.PURE_DELETION.value,
            icon="🗑️",
            title=f"Removed ({len(deleted)} unused symbol{'s' if len(deleted) != 1 else ''})",
            files=deleted_files[:10],
            detail=f"Removed {len(deleted)} symbol(s) with 0 external callers.",
        ))
        deleted_set = {c.file for c in deleted}
        remaining = [c for c in remaining if c.file not in deleted_set or c.kind != "removed"]

    return edge_blocks, remaining


def _detect_bulk_rename(changes: list["StructuralChange"]) -> EdgeCaseBlock | None:
    """Detect bulk rename/move patterns (§11.5.3).

    Heuristic: >10 files with the same kind ('moved') or many body changes
    with minimal per-file diff.
    """
    moved = [c for c in changes if c.kind == "moved"]
    if len(moved) > 10:
        files = [c.file for c in moved]
        return EdgeCaseBlock(
            kind=EdgeCaseKind.BULK_RENAME.value,
            icon="📦",
            title=f"Bulk rename/move ({len(moved)} files)",
            files=files[:10],
            detail="All import paths updated. No signature changes. Structural risk: negligible.",
        )
    return None


# ---------------------------------------------------------------------------
# Aggregation (§11.6)
# ---------------------------------------------------------------------------


def aggregate_by_community(
    changes: list["StructuralChange"],
    file_to_community: dict[str, str],
) -> list[CommunityRollup]:
    """Group body changes by community into rollup summaries (§11.6.1).

    Used when body changes exceed the cognitive-load cap.
    """
    grouped: dict[str, list["StructuralChange"]] = {}
    for ch in changes:
        comm = file_to_community.get(ch.file, "unclustered")
        grouped.setdefault(comm, []).append(ch)

    rollups: list[CommunityRollup] = []
    for name, members in sorted(grouped.items(), key=lambda kv: -sum(c.risk for c in kv[1])):
        risks = [c.risk for c in members]
        avg_risk = sum(risks) / len(risks) if risks else 0.0
        highest = max(members, key=lambda c: c.risk)
        rollups.append(CommunityRollup(
            name=name,
            change_count=len(members),
            avg_risk=round(avg_risk, 2),
            highest_risk_symbol=highest.symbol,
            highest_risk=highest.risk,
            summary=_community_summary(name, members),
        ))

    return rollups


def _community_summary(name: str, members: list["StructuralChange"]) -> str:
    """Build a one-line community rollup summary."""
    all_verified = all(
        c.ref_tiers.get("unverified", 0) == 0
        for c in members
        if c.ref_count > 0
    )
    high_caller = [c for c in members if c.ref_count > 10]

    parts: list[str] = []
    if all_verified and members:
        parts.append("All callers verified.")
    elif not all_verified:
        unverified_count = sum(1 for c in members if c.ref_tiers.get("unverified", 0) > 0)
        parts.append(f"{unverified_count} change(s) with unverified callers.")
    if high_caller:
        parts.append(f"Includes {len(high_caller)} change(s) with >10 callers.")

    return " ".join(parts) if parts else "Internal implementation changes."


def detect_pattern_groups(changes: list["StructuralChange"]) -> list[PatternGroup]:
    """Detect repeated structural patterns across changes (§11.6.2).

    If multiple changes share the same summary pattern, group them.
    """
    if len(changes) < 3:
        return []

    # Group by normalized summary
    by_summary: dict[str, list["StructuralChange"]] = {}
    for ch in changes:
        key = _normalize_summary(ch.summary or "")
        if key:
            by_summary.setdefault(key, []).append(ch)

    groups: list[PatternGroup] = []
    for pattern, members in by_summary.items():
        if len(members) >= 3:
            groups.append(PatternGroup(
                pattern=pattern,
                count=len(members),
                files=[c.file for c in members],
                summary=f"{len(members)} changes share the pattern: {pattern}",
            ))

    return groups


def _normalize_summary(summary: str) -> str:
    """Normalize a change summary for pattern matching."""
    # Remove specific identifiers to find common patterns
    s = re.sub(r"`[^`]+`", "`SYMBOL`", summary)
    s = re.sub(r"'[^']+'", "'SYMBOL'", s)
    s = re.sub(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", "SYMBOL", s)  # CamelCase
    s = re.sub(r"\b[a-z_]+\b", lambda m: m.group() if len(m.group()) < 4 else "WORD", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Small-job detection (§11.5.6)
# ---------------------------------------------------------------------------


def is_small_job(changes: list["StructuralChange"]) -> bool:
    """Check if a job is small enough for collapsed single-paragraph verdict."""
    structural = [c for c in changes if c.category != "non-structural"]
    breaking = [c for c in changes if c.category == "breaking"]
    unknown = any(c.ref_tiers.get("unverified", 0) > 0 for c in changes)
    return len(structural) <= 5 and len(breaking) == 0 and not unknown


# ---------------------------------------------------------------------------
# Orchestrator — assemble the full classification
# ---------------------------------------------------------------------------


class StoryClassification(TypedDict, total=False):
    edge_cases: list[EdgeCaseBlock]
    density_map: dict[str, str]
    community_rollups: list[CommunityRollup]
    pattern_groups: list[PatternGroup]
    collapsed: bool
    remaining_changes: list[Any]


def classify_story(
    changes: list["StructuralChange"],
    file_to_community: dict[str, str] | None = None,
) -> StoryClassification:
    """Full classification pipeline — density, edge cases, aggregation.

    Returns a StoryClassification dict with all the classification results
    that the review-story endpoint needs.
    """
    # 1. Edge-case detection (§11.5)
    edge_blocks, remaining = detect_edge_cases(changes)

    # 2. Small-job check (§11.5.6)
    collapsed = is_small_job(remaining)

    # 3. Density classification (§11.4)
    density_map: dict[str, str] = {}
    for ch in remaining:
        level = classify_density(ch, remaining)
        density_map[ch.file + "::" + (ch.symbol or "")] = level.value

    # 4. Aggregation (§11.6) — only when over budget
    body_changes = [c for c in remaining if c.category == "body"]
    additive_changes = [c for c in remaining if c.category == "additive"]

    community_rollups: list[CommunityRollup] = []
    if len(body_changes) > _BODY_CAP and file_to_community:
        community_rollups = aggregate_by_community(body_changes, file_to_community)

    pattern_groups = detect_pattern_groups(body_changes + additive_changes)

    return StoryClassification(
        edge_cases=edge_blocks,
        density_map=density_map,
        community_rollups=community_rollups,
        pattern_groups=pattern_groups,
        collapsed=collapsed,
        remaining_changes=[c for c in remaining],
    )
