"""Integration tests for the V8 layered diff endpoints.

- GET /api/jobs/{job_id}/line-coverage
- GET /api/jobs/{job_id}/motivations
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

    from backend.tests.integration.conftest import SeedJobFn


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/line-coverage
# ---------------------------------------------------------------------------


class TestLineCoverage:
    """GET /api/jobs/{job_id}/line-coverage"""

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_coderecon_disabled(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
    ) -> None:
        job_id = await seed_job()
        resp = await client.get(
            f"/api/jobs/{job_id}/line-coverage",
            params={"file_path": "src/foo.py"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["jobId"] == job_id
        assert body["filePath"] == "src/foo.py"
        assert body["available"] is False

    @pytest.mark.asyncio
    async def test_returns_unavailable_for_job_without_repo(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
    ) -> None:
        """Jobs without a repo field should get available=false."""
        job_id = await seed_job()
        resp = await client.get(
            f"/api/jobs/{job_id}/line-coverage",
            params={"file_path": "src/bar.py"},
        )
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    @pytest.mark.asyncio
    async def test_requires_file_path_param(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
    ) -> None:
        job_id = await seed_job()
        resp = await client.get(f"/api/jobs/{job_id}/line-coverage")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_job(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get(
            "/api/jobs/nonexistent-id/line-coverage",
            params={"file_path": "x.py"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_response_structure_when_available(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
        mock_coderecon_service: AsyncMock,
    ) -> None:
        """When coderecon is available and returns data, response has all fields."""
        # Reconfigure the mock for this test
        mock_coderecon_service.available = True

        # Create a mock result
        mock_result = AsyncMock()
        mock_result.covered_lines = [1, 2, 5]
        mock_result.uncovered_lines = [3, 4]
        mock_result.total_instrumented = 5
        mock_result.line_rate = 0.6
        mock_result.tests_by_line = {1: ["test_foo"], 2: ["test_bar", "test_baz"]}
        mock_coderecon_service.line_coverage.return_value = mock_result

        job_id = await seed_job(worktree_path="wt-test")
        resp = await client.get(
            f"/api/jobs/{job_id}/line-coverage",
            params={"file_path": "src/module.py"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["coveredLines"] == [1, 2, 5]
        assert body["uncoveredLines"] == [3, 4]
        assert body["totalInstrumented"] == 5
        assert body["lineRate"] == 0.6
        assert "1" in body["testsByLine"]
        assert len(body["testsByLine"]["1"]) == 1
        assert body["testsByLine"]["1"][0]["name"] == "test_foo"


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/motivations
# ---------------------------------------------------------------------------


class TestMotivations:
    """GET /api/jobs/{job_id}/motivations"""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_spans(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
    ) -> None:
        job_id = await seed_job()
        resp = await client.get(f"/api/jobs/{job_id}/motivations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["jobId"] == job_id
        assert body["fileMotivations"] == {}
        assert body["hunkMotivations"] == {}

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_job(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get("/api/jobs/ghost-id/motivations")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_response_structure(
        self,
        client: AsyncClient,
        seed_job: SeedJobFn,
    ) -> None:
        """Response uses camelCase field names."""
        job_id = await seed_job()
        resp = await client.get(f"/api/jobs/{job_id}/motivations")
        body = resp.json()
        assert "jobId" in body
        assert "fileMotivations" in body
        assert "hunkMotivations" in body
