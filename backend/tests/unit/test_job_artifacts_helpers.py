"""Tests for backend.api.job_artifacts — pure structural diff helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.api.job_artifacts import (
    _classify_category,
    _compute_merge_confidence,
    _compute_risk,
    _compute_triage,
    _translate_ref_tiers,
)
from backend.models.api_schemas import StructuralChange


# ---------------------------------------------------------------------------
# Fake coderecon objects for _classify_category / _translate_ref_tiers
# ---------------------------------------------------------------------------


@dataclass
class FakeRefTiers:
    proven: int = 0
    strong: int = 0
    anchored: int = 0
    unknown: int = 0


@dataclass
class FakeImpact:
    reference_count: int = 0
    affected_test_files: list[str] = field(default_factory=list)
    ref_tiers: FakeRefTiers | None = None


@dataclass
class FakeChange:
    change: str = "modified"
    name: str = "foo"
    qualified_name: str | None = "module.foo"
    path: str = "src/app.py"
    change_preview: str | None = "Modified foo"
    old_sig: str | None = None
    new_sig: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    impact: FakeImpact | None = None


# ---------------------------------------------------------------------------
# _classify_category
# ---------------------------------------------------------------------------


class TestClassifyCategory:
    def test_removed_with_refs_breaking(self):
        c = FakeChange(change="removed", impact=FakeImpact(reference_count=3))
        assert _classify_category(c) == "breaking"

    def test_removed_no_refs(self):
        c = FakeChange(change="removed", impact=FakeImpact(reference_count=0))
        assert _classify_category(c) == "non-structural"

    def test_modified_sig_change_breaking(self):
        c = FakeChange(change="modified", old_sig="def foo(a)", new_sig="def foo(a, b)", impact=FakeImpact())
        assert _classify_category(c) == "breaking"

    def test_modified_no_sig_change_body(self):
        c = FakeChange(change="modified", old_sig="def foo(a)", new_sig="def foo(a)", impact=FakeImpact())
        assert _classify_category(c) == "body"

    def test_modified_no_sigs_body(self):
        c = FakeChange(change="modified", impact=FakeImpact())
        assert _classify_category(c) == "body"

    def test_added_additive(self):
        c = FakeChange(change="added", impact=FakeImpact())
        assert _classify_category(c) == "additive"

    def test_moved_body(self):
        c = FakeChange(change="moved", impact=FakeImpact())
        assert _classify_category(c) == "body"

    def test_unknown_kind(self):
        c = FakeChange(change="unknown_kind", impact=FakeImpact())
        assert _classify_category(c) == "non-structural"


# ---------------------------------------------------------------------------
# _translate_ref_tiers
# ---------------------------------------------------------------------------


class TestTranslateRefTiers:
    def test_all_tiers(self):
        tiers = FakeRefTiers(proven=5, strong=3, anchored=2, unknown=1)
        result = _translate_ref_tiers(tiers)
        assert result["verified"] == 5
        assert result["inferred"] == 5  # strong + anchored
        assert result["unverified"] == 1

    def test_only_proven(self):
        tiers = FakeRefTiers(proven=3)
        result = _translate_ref_tiers(tiers)
        assert result == {"verified": 3}

    def test_empty(self):
        tiers = FakeRefTiers()
        assert _translate_ref_tiers(tiers) == {}


# ---------------------------------------------------------------------------
# _compute_risk
# ---------------------------------------------------------------------------


class TestComputeRisk:
    def test_breaking_unverified_no_tests(self):
        risk = _compute_risk("breaking", {"unverified": 5}, [])
        # severity=1.0, unknown_ratio=1.0, test_gap=1.0
        assert risk == 1.0

    def test_additive_verified_with_tests(self):
        risk = _compute_risk("additive", {"verified": 5}, ["test.py"])
        # severity=0.1, unknown_ratio=0.0, test_gap=0.0
        assert risk == pytest.approx(0.04)

    def test_body_no_refs(self):
        risk = _compute_risk("body", {}, [])
        # severity=0.5, unknown_ratio=0.0, test_gap=1.0
        assert risk == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# _compute_triage
# ---------------------------------------------------------------------------


class TestComputeTriage:
    def test_counts(self):
        changes = [
            StructuralChange(file="a.py", kind="modified", category="breaking"),
            StructuralChange(file="b.py", kind="modified", category="body"),
            StructuralChange(file="c.py", kind="modified", category="body"),
            StructuralChange(file="d.py", kind="added", category="additive"),
        ]
        triage = _compute_triage(changes)
        assert triage == {"breaking": 1, "body": 2, "additive": 1}

    def test_empty(self):
        assert _compute_triage([]) == {}


# ---------------------------------------------------------------------------
# _compute_merge_confidence
# ---------------------------------------------------------------------------


class TestComputeMergeConfidence:
    def test_all_verified_high(self):
        changes = [
            StructuralChange(file="a.py", kind="modified", category="body", ref_tiers={"verified": 3}, test_files=["test.py"]),
        ]
        assert _compute_merge_confidence(changes) == "HIGH"

    def test_new_cycles_low(self):
        assert _compute_merge_confidence([], has_new_cycles=True) == "LOW"

    def test_unverified_breaking_low(self):
        changes = [
            StructuralChange(file="a.py", kind="modified", category="breaking", ref_tiers={"unverified": 1}),
        ]
        assert _compute_merge_confidence(changes) == "LOW"

    def test_unknown_refs_medium(self):
        changes = [
            StructuralChange(file="a.py", kind="modified", category="body", ref_tiers={"unverified": 1}),
        ]
        assert _compute_merge_confidence(changes) == "MEDIUM"

    def test_untested_breaking_medium(self):
        changes = [
            StructuralChange(file="a.py", kind="modified", category="breaking", ref_tiers={"verified": 3}),
        ]
        assert _compute_merge_confidence(changes) == "MEDIUM"

    def test_empty_high(self):
        assert _compute_merge_confidence([]) == "HIGH"
