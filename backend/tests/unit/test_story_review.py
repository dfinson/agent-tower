"""Tests for backend.services.story.review — density, edge-case, and aggregation logic."""

from __future__ import annotations

import pytest

from backend.models.api_schemas import StructuralChange
from backend.services.story.review import (
    CommunityRollup,
    DensityLevel,
    EdgeCaseKind,
    PatternGroup,
    _community_summary,
    _detect_bulk_rename,
    _find_production_mirror,
    _is_test_file,
    _normalize_summary,
    aggregate_by_community,
    classify_density,
    classify_story,
    detect_edge_cases,
    detect_pattern_groups,
    is_small_job,
)


# ---------------------------------------------------------------------------
# Helpers — build StructuralChange objects with minimal args
# ---------------------------------------------------------------------------


def _sc(
    *,
    file: str = "src/app.py",
    kind: str = "modified",
    symbol: str | None = "MyClass",
    category: str = "body",
    ref_count: int = 0,
    ref_tiers: dict | None = None,
    risk: float = 0.0,
    summary: str | None = None,
) -> StructuralChange:
    return StructuralChange(
        file=file,
        kind=kind,
        symbol=symbol,
        category=category,
        ref_count=ref_count,
        ref_tiers=ref_tiers or {},
        risk=risk,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_test_prefix(self):
        assert _is_test_file("test_foo.py") is True

    def test_test_suffix_py(self):
        assert _is_test_file("foo_test.py") is True

    def test_test_suffix_ts(self):
        assert _is_test_file("App.test.ts") is True

    def test_spec_suffix_tsx(self):
        assert _is_test_file("App.spec.tsx") is True

    def test_tests_dir(self):
        assert _is_test_file("src/tests/helper.py") is True

    def test_dunder_tests(self):
        assert _is_test_file("src/__tests__/App.jsx") is True

    def test_production_file(self):
        assert _is_test_file("src/app.py") is False

    def test_test_dir(self):
        assert _is_test_file("src/test/helper.py") is True


# ---------------------------------------------------------------------------
# _find_production_mirror
# ---------------------------------------------------------------------------


class TestFindProductionMirror:
    def test_test_prefix(self):
        prod_files = {"src/foo.py"}
        assert _find_production_mirror("tests/test_foo.py", prod_files) == "foo.py"

    def test_test_suffix_ts(self):
        prod_files = {"src/App.ts"}
        result = _find_production_mirror("src/App.test.ts", prod_files)
        assert result is not None

    def test_spec_suffix_tsx(self):
        prod_files = {"src/App.tsx"}
        result = _find_production_mirror("src/App.spec.tsx", prod_files)
        assert result is not None

    def test_no_match(self):
        prod_files = {"src/other.py"}
        assert _find_production_mirror("tests/test_foo.py", prod_files) is None


# ---------------------------------------------------------------------------
# classify_density
# ---------------------------------------------------------------------------


class TestClassifyDensity:
    def test_unverified_refs_full(self):
        ch = _sc(ref_tiers={"unverified": 1}, ref_count=1)
        assert classify_density(ch, [ch]) == DensityLevel.FULL

    def test_breaking_full(self):
        ch = _sc(category="breaking")
        assert classify_density(ch, [ch]) == DensityLevel.FULL

    def test_high_ref_breaking(self):
        ch = _sc(category="breaking", ref_count=15)
        assert classify_density(ch, [ch]) == DensityLevel.FULL

    def test_high_ref_non_breaking(self):
        ch = _sc(category="body", ref_count=15)
        assert classify_density(ch, [ch]) == DensityLevel.SUMMARY

    def test_additive_no_refs_count_only(self):
        ch = _sc(category="additive", ref_count=0)
        assert classify_density(ch, [ch]) == DensityLevel.COUNT_ONLY

    def test_non_structural_omitted(self):
        ch = _sc(category="non-structural")
        assert classify_density(ch, [ch]) == DensityLevel.OMITTED

    def test_test_file_mirrors_production_omitted(self):
        prod = _sc(file="src/foo.py", category="body")
        test = _sc(file="tests/test_foo.py", category="body")
        assert classify_density(test, [prod, test]) == DensityLevel.OMITTED

    def test_verified_low_risk_summary(self):
        ch = _sc(ref_count=3, ref_tiers={"verified": 3}, risk=0.1)
        assert classify_density(ch, [ch]) == DensityLevel.SUMMARY

    def test_body_default_summary(self):
        ch = _sc(category="body", ref_count=1, ref_tiers={"inferred": 1})
        assert classify_density(ch, [ch]) == DensityLevel.SUMMARY


# ---------------------------------------------------------------------------
# detect_edge_cases
# ---------------------------------------------------------------------------


class TestDetectEdgeCases:
    def test_doc_files_extracted(self):
        changes = [_sc(file="docs/guide.md"), _sc(file="src/app.py")]
        blocks, remaining = detect_edge_cases(changes)
        assert len(blocks) >= 1
        assert any(b["kind"] == EdgeCaseKind.DOCUMENTATION.value for b in blocks)
        assert len(remaining) == 1
        assert remaining[0].file == "src/app.py"

    def test_generated_files_extracted(self):
        changes = [_sc(file="alembic/versions/0001_init.py"), _sc(file="src/app.py")]
        blocks, remaining = detect_edge_cases(changes)
        assert any(b["kind"] == EdgeCaseKind.GENERATED.value for b in blocks)

    def test_vendor_files_extracted(self):
        changes = [_sc(file="vendor/lib/code.py"), _sc(file="src/app.py")]
        blocks, remaining = detect_edge_cases(changes)
        assert any(b["kind"] == EdgeCaseKind.VENDOR.value for b in blocks)

    def test_lock_files_omitted(self):
        changes = [_sc(file="package-lock.json"), _sc(file="src/app.py")]
        blocks, remaining = detect_edge_cases(changes)
        assert len(remaining) == 1
        assert remaining[0].file == "src/app.py"

    def test_pure_deletions_grouped(self):
        # Need at least 3 zero-ref removed items
        changes = [
            _sc(file="a.py", kind="removed", ref_count=0),
            _sc(file="b.py", kind="removed", ref_count=0),
            _sc(file="c.py", kind="removed", ref_count=0),
            _sc(file="d.py"),
        ]
        blocks, remaining = detect_edge_cases(changes)
        assert any(b["kind"] == EdgeCaseKind.PURE_DELETION.value for b in blocks)


# ---------------------------------------------------------------------------
# _detect_bulk_rename
# ---------------------------------------------------------------------------


class TestDetectBulkRename:
    def test_no_bulk(self):
        changes = [_sc(kind="moved") for _ in range(5)]
        assert _detect_bulk_rename(changes) is None

    def test_bulk_detected(self):
        changes = [_sc(file=f"file{i}.py", kind="moved") for i in range(15)]
        result = _detect_bulk_rename(changes)
        assert result is not None
        assert result["kind"] == EdgeCaseKind.BULK_RENAME.value


# ---------------------------------------------------------------------------
# aggregate_by_community
# ---------------------------------------------------------------------------


class TestAggregateByCommunity:
    def test_basic_grouping(self):
        changes = [
            _sc(file="a.py", risk=0.5, symbol="A", ref_count=1, ref_tiers={"verified": 1}),
            _sc(file="b.py", risk=0.3, symbol="B", ref_count=1, ref_tiers={"verified": 1}),
            _sc(file="c.py", risk=0.8, symbol="C"),
        ]
        mapping = {"a.py": "core", "b.py": "core", "c.py": "utils"}
        rollups = aggregate_by_community(changes, mapping)
        assert len(rollups) == 2
        names = {r["name"] for r in rollups}
        assert "core" in names
        assert "utils" in names

    def test_unclustered_fallback(self):
        changes = [_sc(file="x.py", symbol="X")]
        rollups = aggregate_by_community(changes, {})
        assert rollups[0]["name"] == "unclustered"


# ---------------------------------------------------------------------------
# _community_summary
# ---------------------------------------------------------------------------


class TestCommunitySummary:
    def test_all_verified(self):
        members = [
            _sc(ref_count=3, ref_tiers={"verified": 3}),
            _sc(ref_count=1, ref_tiers={"verified": 1}),
        ]
        result = _community_summary("core", members)
        assert "All callers verified" in result

    def test_unverified(self):
        members = [_sc(ref_count=2, ref_tiers={"unverified": 1, "verified": 1})]
        result = _community_summary("core", members)
        assert "unverified callers" in result

    def test_high_callers(self):
        members = [_sc(ref_count=15, ref_tiers={"verified": 15})]
        result = _community_summary("core", members)
        assert ">10 callers" in result

    def test_empty_default(self):
        result = _community_summary("core", [])
        assert result == "Internal implementation changes."


# ---------------------------------------------------------------------------
# detect_pattern_groups
# ---------------------------------------------------------------------------


class TestDetectPatternGroups:
    def test_no_patterns_small_list(self):
        changes = [_sc(summary="Added foo"), _sc(summary="Added bar")]
        assert detect_pattern_groups(changes) == []

    def test_patterns_detected(self):
        # 3+ changes with the same normalized summary pattern
        changes = [
            _sc(summary="Added new method `doStuff`", file=f"f{i}.py") for i in range(4)
        ]
        groups = detect_pattern_groups(changes)
        assert len(groups) >= 1
        assert groups[0]["count"] >= 3


# ---------------------------------------------------------------------------
# _normalize_summary
# ---------------------------------------------------------------------------


class TestNormalizeSummary:
    def test_backtick_symbols(self):
        result = _normalize_summary("Changed `MyClass` method")
        assert "`SYMBOL`" in result

    def test_camel_case(self):
        result = _normalize_summary("Renamed MyFooBar to something")
        assert "SYMBOL" in result


# ---------------------------------------------------------------------------
# is_small_job
# ---------------------------------------------------------------------------


class TestIsSmallJob:
    def test_small(self):
        changes = [_sc(category="body") for _ in range(3)]
        assert is_small_job(changes) is True

    def test_too_many_structural(self):
        changes = [_sc(category="body") for _ in range(8)]
        assert is_small_job(changes) is False

    def test_has_breaking(self):
        changes = [_sc(category="breaking")]
        assert is_small_job(changes) is False

    def test_unverified_refs(self):
        changes = [_sc(ref_tiers={"unverified": 1})]
        assert is_small_job(changes) is False

    def test_non_structural_ignored(self):
        changes = [_sc(category="non-structural") for _ in range(10)]
        assert is_small_job(changes) is True


# ---------------------------------------------------------------------------
# classify_story (orchestrator)
# ---------------------------------------------------------------------------


class TestClassifyStory:
    def test_basic_pipeline(self):
        changes = [
            _sc(file="src/app.py", category="body", symbol="App"),
            _sc(file="docs/README.md", category="body", symbol="ReadMe"),
        ]
        result = classify_story(changes)
        assert "edge_cases" in result
        assert "density_map" in result
        assert "collapsed" in result

    def test_with_community_map(self):
        changes = [_sc(file=f"f{i}.py", category="body", symbol=f"S{i}") for i in range(15)]
        mapping = {f"f{i}.py": "core" for i in range(15)}
        result = classify_story(changes, file_to_community=mapping)
        assert "community_rollups" in result
