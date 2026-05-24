"""Tests for coverage ingestion pipeline — Trigger A (drain_coverage_scan) and Trigger B (checkpoint tool)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import TrailConfig
from backend.services.trail.enricher import TrailEnricher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(job_rows=None):
    """Build a mock async_sessionmaker that returns rows from 'jobs' query."""
    mock_session = AsyncMock()

    if job_rows is not None:
        # Mock execute to return job rows
        result = MagicMock()
        result.mappings.return_value.all.return_value = job_rows
        mock_session.execute = AsyncMock(return_value=result)

    mock_factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = mock_session
    ctx.__aexit__.return_value = False
    mock_factory.return_value = ctx
    return mock_factory


def _make_enricher(
    *,
    coderecon: AsyncMock | None = None,
    job_rows=None,
) -> TrailEnricher:
    """Construct a TrailEnricher with mocked dependencies for coverage tests."""
    session_factory = _make_session_factory(job_rows)
    event_bus = AsyncMock()
    enricher = TrailEnricher(
        session_factory=session_factory,
        event_bus=event_bus,
        sidecar_sessions=AsyncMock(),
        config=TrailConfig(),
        coderecon=coderecon,
    )
    enricher._repo = AsyncMock()
    return enricher


# ---------------------------------------------------------------------------
# Trigger A: drain_coverage_scan
# ---------------------------------------------------------------------------


class TestDrainCoverageScan:
    """Tests for TrailEnricher.drain_coverage_scan()."""

    @pytest.mark.asyncio
    async def test_no_coderecon_returns_zero(self):
        """If CodeRecon is not configured, return 0."""
        enricher = _make_enricher(coderecon=None)
        assert await enricher.drain_coverage_scan() == 0

    @pytest.mark.asyncio
    async def test_no_coverage_file_returns_zero(self):
        """If no coverage report exists in the worktree, return 0."""
        coderecon = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)
            result = await enricher.drain_coverage_scan()
            assert result == 0

    @pytest.mark.asyncio
    async def test_ingests_coverage_json(self):
        """When coverage.json exists, it gets ingested."""
        coderecon = AsyncMock()
        ingest_result = MagicMock()
        ingest_result.files_covered = 5
        coderecon.ensure_repo_indexed = AsyncMock(return_value="my-repo")
        coderecon.register_worktree = AsyncMock()
        coderecon.ingest_coverage = AsyncMock(return_value=ingest_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a coverage.json file
            cov_file = Path(tmpdir) / "coverage.json"
            cov_file.write_text(json.dumps({"meta": {}, "files": {"a.py": {}}}))

            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)
            result = await enricher.drain_coverage_scan()

            assert result == 1
            coderecon.ingest_coverage.assert_called_once()
            call_args = coderecon.ingest_coverage.call_args
            assert call_args[0][1] == str(cov_file)

    @pytest.mark.asyncio
    async def test_skips_already_ingested(self):
        """Same mtime file is not re-ingested."""
        coderecon = AsyncMock()
        ingest_result = MagicMock()
        ingest_result.files_covered = 3
        coderecon.ensure_repo_indexed = AsyncMock(return_value="my-repo")
        coderecon.register_worktree = AsyncMock()
        coderecon.ingest_coverage = AsyncMock(return_value=ingest_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            cov_file = Path(tmpdir) / "coverage.json"
            cov_file.write_text(json.dumps({"meta": {}}))

            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)

            # First call ingests
            assert await enricher.drain_coverage_scan() == 1
            # Second call with same mtime skips
            assert await enricher.drain_coverage_scan() == 0
            assert coderecon.ingest_coverage.call_count == 1

    @pytest.mark.asyncio
    async def test_ingests_lcov(self):
        """lcov.info in the worktree gets picked up."""
        coderecon = AsyncMock()
        ingest_result = MagicMock()
        ingest_result.files_covered = 2
        coderecon.ensure_repo_indexed = AsyncMock(return_value="my-repo")
        coderecon.register_worktree = AsyncMock()
        coderecon.ingest_coverage = AsyncMock(return_value=ingest_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            lcov_file = Path(tmpdir) / "lcov.info"
            lcov_file.write_text("SF:src/main.py\nDA:1,1\nend_of_record\n")

            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)
            result = await enricher.drain_coverage_scan()

            assert result == 1

    @pytest.mark.asyncio
    async def test_skips_empty_report(self):
        """Empty coverage files (0 bytes) are ignored."""
        coderecon = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            cov_file = Path(tmpdir) / "coverage.json"
            cov_file.write_text("")  # 0 bytes

            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)
            result = await enricher.drain_coverage_scan()

            assert result == 0

    @pytest.mark.asyncio
    async def test_skips_zero_files_covered(self):
        """If ingest returns 0 files_covered, don't mark as ingested."""
        coderecon = AsyncMock()
        ingest_result = MagicMock()
        ingest_result.files_covered = 0
        coderecon.ensure_repo_indexed = AsyncMock(return_value="my-repo")
        coderecon.register_worktree = AsyncMock()
        coderecon.ingest_coverage = AsyncMock(return_value=ingest_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            cov_file = Path(tmpdir) / "coverage.json"
            cov_file.write_text(json.dumps({"meta": {}}))

            job_rows = [{"id": "j1", "repo": "/repo", "worktree_path": tmpdir}]
            enricher = _make_enricher(coderecon=coderecon, job_rows=job_rows)
            result = await enricher.drain_coverage_scan()

            assert result == 0


# ---------------------------------------------------------------------------
# Trigger B: checkpoint tool auto-ingest
# ---------------------------------------------------------------------------


class TestCheckpointCoverageIngest:
    """Tests for _try_ingest_coverage called after checkpoint."""

    @pytest.mark.asyncio
    async def test_ingests_after_checkpoint(self):
        """_try_ingest_coverage finds and ingests a report."""
        from backend.services.coderecon.coderecon_tools import _try_ingest_coverage

        service = AsyncMock()
        ingest_result = MagicMock()
        ingest_result.files_covered = 10
        service.ingest_coverage = AsyncMock(return_value=ingest_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            cov = Path(tmpdir) / "coverage.json"
            cov.write_text(json.dumps({"files": {"main.py": {}}}))

            await _try_ingest_coverage(service, "my-repo", tmpdir)
            service.ingest_coverage.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_report_no_call(self):
        """If no report file exists, ingest is not called."""
        from backend.services.coderecon.coderecon_tools import _try_ingest_coverage

        service = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            await _try_ingest_coverage(service, "my-repo", tmpdir)
            service.ingest_coverage.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_ingest_failure_gracefully(self):
        """If ingest raises, it doesn't propagate."""
        from backend.services.coderecon.coderecon_tools import _try_ingest_coverage

        service = AsyncMock()
        service.ingest_coverage = AsyncMock(side_effect=RuntimeError("boom"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cov = Path(tmpdir) / "coverage.json"
            cov.write_text(json.dumps({"files": {}}))

            # Should not raise
            await _try_ingest_coverage(service, "my-repo", tmpdir)
