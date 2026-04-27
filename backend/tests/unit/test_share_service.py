"""Tests for ShareService — in-memory share token management."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from backend.services.share_service import InvalidShareTokenError, ShareService


class TestShareService:
    def test_create_token_returns_entry(self) -> None:
        svc = ShareService(ttl=60)
        entry = svc.create_token("job-1")
        assert entry.job_id == "job-1"
        assert len(entry.token) > 20  # urlsafe token is long
        assert entry.ttl == 60

    def test_validate_valid_token(self) -> None:
        svc = ShareService(ttl=60)
        entry = svc.create_token("job-1")
        assert svc.validate(entry.token) == "job-1"

    def test_validate_missing_token(self) -> None:
        svc = ShareService()
        with pytest.raises(InvalidShareTokenError):
            svc.validate("nonexistent")

    def test_validate_expired_token(self) -> None:
        svc = ShareService(ttl=1)
        entry = svc.create_token("job-1")
        # Fast-forward monotonic time past TTL
        with patch("backend.services.share_service.time") as mock_time:
            # created_at is real monotonic; make "now" be 100s later
            mock_time.monotonic.return_value = entry.created_at + 100
            with pytest.raises(InvalidShareTokenError):
                svc.validate(entry.token)

    def test_revoke_existing(self) -> None:
        svc = ShareService()
        entry = svc.create_token("job-1")
        assert svc.revoke(entry.token) is True
        with pytest.raises(InvalidShareTokenError):
            svc.validate(entry.token)

    def test_revoke_missing(self) -> None:
        svc = ShareService()
        assert svc.revoke("no-such-token") is False

    def test_evict_expired_on_create(self) -> None:
        svc = ShareService(ttl=1)
        entry1 = svc.create_token("job-1")
        # Manually expire entry1
        with patch("backend.services.share_service.time") as mock_time:
            mock_time.monotonic.return_value = entry1.created_at + 100
            # Creating a new token triggers eviction
            svc.create_token("job-2")
        # entry1 should have been evicted
        with pytest.raises(InvalidShareTokenError):
            svc.validate(entry1.token)

    def test_multiple_tokens_for_same_job(self) -> None:
        svc = ShareService()
        t1 = svc.create_token("job-1")
        t2 = svc.create_token("job-1")
        assert t1.token != t2.token
        assert svc.validate(t1.token) == "job-1"
        assert svc.validate(t2.token) == "job-1"
