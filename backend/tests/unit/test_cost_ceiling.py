"""Unit tests for CodePlane's native USD cost-ceiling ``PolicyAssessor``.

``JobSpendCeilingAssessor`` extends TraceForge in its own idiom (the documented
``PolicyAssessor`` protocol) so CodePlane's dollar spend ceiling is preserved
without a charter-forbidden CP↔TF bridge. These assert the elevate-only threshold
behavior and the fail-open spend reader in isolation (no pipeline needed).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

from traceforge.governance.rules import RecommendedAction

from backend.services.action_policy.cost_ceiling import (
    CEILING_REASON_CODE,
    WARN_REASON_CODE,
    JobSpendCeilingAssessor,
    make_job_spend_reader,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime.now(UTC)


def _ctx(session_id: str = "j1") -> SimpleNamespace:
    """Minimal EnrichmentContext stand-in — the assessor only reads ctx.event.session_id."""
    return SimpleNamespace(event=SimpleNamespace(session_id=session_id))


def test_escalates_at_or_above_ceiling() -> None:
    a = JobSpendCeilingAssessor(50.0, 20.0, lambda _sid: 100.0)
    decision = a.assess(_ctx(), _NOW)
    assert decision is not None
    assert decision.action == RecommendedAction.ESCALATE
    assert decision.reason_code == CEILING_REASON_CODE


def test_ceiling_boundary_is_inclusive() -> None:
    a = JobSpendCeilingAssessor(50.0, 20.0, lambda _sid: 50.0)
    decision = a.assess(_ctx(), _NOW)
    assert decision is not None
    assert decision.action == RecommendedAction.ESCALATE


def test_warns_between_warn_and_ceiling() -> None:
    a = JobSpendCeilingAssessor(50.0, 20.0, lambda _sid: 20.0)
    decision = a.assess(_ctx(), _NOW)
    assert decision is not None
    assert decision.action == RecommendedAction.WARN
    assert decision.reason_code == WARN_REASON_CODE


def test_no_decision_below_warn() -> None:
    a = JobSpendCeilingAssessor(50.0, 20.0, lambda _sid: 5.0)
    assert a.assess(_ctx(), _NOW) is None


def test_ceiling_only_no_warn_line() -> None:
    a = JobSpendCeilingAssessor(50.0, None, lambda _sid: 30.0)
    # 30 < 50 and no warn line → abstain.
    assert a.assess(_ctx(), _NOW) is None
    a2 = JobSpendCeilingAssessor(50.0, None, lambda _sid: 60.0)
    d = a2.assess(_ctx(), _NOW)
    assert d is not None and d.action == RecommendedAction.ESCALATE


def test_disabled_when_no_thresholds() -> None:
    a = JobSpendCeilingAssessor(None, None, lambda _sid: 1_000_000.0)
    assert a.assess(_ctx(), _NOW) is None


def test_fails_open_on_reader_error() -> None:
    def boom(_sid: str) -> float:
        raise RuntimeError("telemetry down")

    a = JobSpendCeilingAssessor(50.0, 20.0, boom)
    # A read error must never manufacture a ceiling breach → abstain (fail open).
    assert a.assess(_ctx(), _NOW) is None


def test_no_decision_without_session_id() -> None:
    a = JobSpendCeilingAssessor(50.0, 20.0, lambda _sid: 100.0)
    assert a.assess(_ctx(session_id=""), _NOW) is None


# ---------------------------------------------------------------------------
# make_job_spend_reader over a throwaway data.db
# ---------------------------------------------------------------------------


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE job_telemetry_summary "
            "(job_id TEXT, session_kind TEXT, total_cost_usd REAL)"
        )
        conn.executemany(
            "INSERT INTO job_telemetry_summary (job_id, session_kind, total_cost_usd) "
            "VALUES (?, ?, ?)",
            [
                ("j1", "job", 12.5),
                ("j1", "sidecar", 99.0),  # must be excluded by the session_kind filter
                ("j2", "job", None),  # null spend → 0.0
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_reader_returns_job_spend(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    reader = make_job_spend_reader(db)
    # Only the session_kind='job' row counts (sidecar row ignored).
    assert reader("j1") == 12.5


def test_reader_missing_row_returns_zero(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    reader = make_job_spend_reader(db)
    assert reader("does-not-exist") == 0.0


def test_reader_null_spend_returns_zero(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    _seed_db(db)
    reader = make_job_spend_reader(db)
    assert reader("j2") == 0.0


def test_reader_fails_open_on_missing_db(tmp_path: Path) -> None:
    # Read-only open of a non-existent file errors → reader returns 0.0 (fail open).
    reader = make_job_spend_reader(tmp_path / "nonexistent.db")
    assert reader("j1") == 0.0
