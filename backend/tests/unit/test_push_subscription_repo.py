"""Tests for PushSubscriptionRepository and PushService persistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base
from backend.persistence.push_subscription_repo import PushSubscriptionRepository


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def session(session_factory) -> AsyncSession:
    async with session_factory() as s:
        yield s


def _make_svc(session_factory):
    from backend.services.sharing.push_service import PushService

    return PushService(
        vapid_private_key="k1",
        vapid_public_key="k2",
        session_factory=session_factory,
    )


def _gone_exc(status: int = 410) -> Exception:
    """Build an exception with a structured response.status_code."""
    exc = Exception(f"HTTP {status}")
    exc.response = SimpleNamespace(status_code=status)  # type: ignore[attr-defined]
    return exc


# ---------------------------------------------------------------------------
# Repository round-trip tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPushSubscriptionRepo:
    async def test_upsert_and_list(self, session: AsyncSession) -> None:
        repo = PushSubscriptionRepository(session)
        await repo.upsert("https://ep.com/1", "p256dh_val", "auth_val")
        await session.commit()
        rows = await repo.list_all()
        assert len(rows) == 1
        assert rows[0]["endpoint"] == "https://ep.com/1"
        assert rows[0]["keys"] == {"p256dh": "p256dh_val", "auth": "auth_val"}

    async def test_upsert_updates_existing(self, session: AsyncSession) -> None:
        repo = PushSubscriptionRepository(session)
        await repo.upsert("https://ep.com/1", "old_p256dh", "old_auth")
        await session.commit()
        await repo.upsert("https://ep.com/1", "new_p256dh", "new_auth")
        await session.commit()
        rows = await repo.list_all()
        assert len(rows) == 1
        assert rows[0]["keys"]["p256dh"] == "new_p256dh"

    async def test_delete(self, session: AsyncSession) -> None:
        repo = PushSubscriptionRepository(session)
        await repo.upsert("https://ep.com/1", "a", "b")
        await session.commit()
        deleted = await repo.delete("https://ep.com/1")
        await session.commit()
        assert deleted is True
        rows = await repo.list_all()
        assert len(rows) == 0

    async def test_delete_nonexistent(self, session: AsyncSession) -> None:
        repo = PushSubscriptionRepository(session)
        deleted = await repo.delete("https://no-such.com/x")
        assert deleted is False

    async def test_delete_many(self, session: AsyncSession) -> None:
        repo = PushSubscriptionRepository(session)
        for i in range(3):
            await repo.upsert(f"https://ep.com/{i}", "p", "a")
        await session.commit()
        count = await repo.delete_many(["https://ep.com/0", "https://ep.com/2"])
        await session.commit()
        assert count == 2
        rows = await repo.list_all()
        assert len(rows) == 1
        assert rows[0]["endpoint"] == "https://ep.com/1"


# ---------------------------------------------------------------------------
# PushService integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPushServiceRestart:
    """Prove subscriptions survive a simulated server restart."""

    async def test_subscription_survives_new_service_instance(self, session_factory) -> None:
        svc1 = _make_svc(session_factory)
        await svc1.subscribe_async({"endpoint": "https://ep.com/persist", "keys": {"p256dh": "abc", "auth": "xyz"}})

        # New instance (simulated restart) loads from DB
        svc2 = _make_svc(session_factory)
        await svc2.load_from_db()
        assert "https://ep.com/persist" in svc2._subscriptions


@pytest.mark.asyncio
class TestPushServiceDbFirst:
    """Verify DB-first write ordering: cache reflects only committed state."""

    async def test_failed_db_write_does_not_update_cache(self, session_factory) -> None:
        svc = _make_svc(session_factory)

        with (
            patch(
                "backend.persistence.database.serialized_write",
                side_effect=RuntimeError("DB write failed"),
            ),
            pytest.raises(RuntimeError, match="DB write failed"),
        ):
            await svc.subscribe_async({"endpoint": "https://ep.com/ghost", "keys": {"p256dh": "a", "auth": "b"}})

        # Cache must NOT contain the subscription
        assert "https://ep.com/ghost" not in svc._subscriptions

    async def test_unsubscribe_deletes_row_even_when_cache_is_cold(self, session_factory) -> None:
        """Unsubscribe must delete the DB row even if the cache has no entry."""
        from backend.persistence.database import serialized_write

        async with serialized_write(session_factory) as session:
            repo = PushSubscriptionRepository(session)
            await repo.upsert("https://ep.com/orphan", "p", "a")

        # Fresh service with empty cache
        svc = _make_svc(session_factory)
        assert "https://ep.com/orphan" not in svc._subscriptions

        await svc.unsubscribe_async("https://ep.com/orphan")

        # DB row must be gone
        async with session_factory() as session:
            repo = PushSubscriptionRepository(session)
            rows = await repo.list_all()
            assert len(rows) == 0


@pytest.mark.asyncio
class TestPushServicePrune:
    """Stale endpoint pruning uses structured status codes."""

    async def test_410_response_prunes_from_cache_and_db(self, session_factory) -> None:
        svc = _make_svc(session_factory)
        await svc.subscribe_async({"endpoint": "https://ep.com/stale", "keys": {"p256dh": "a", "auth": "b"}})

        with patch.object(svc, "_send_one", side_effect=_gone_exc(410)):
            await svc.notify(title="Hi", body="World")

        assert "https://ep.com/stale" not in svc._subscriptions

        async with session_factory() as session:
            repo = PushSubscriptionRepository(session)
            rows = await repo.list_all()
            assert len(rows) == 0

    async def test_404_response_prunes(self, session_factory) -> None:
        svc = _make_svc(session_factory)
        await svc.subscribe_async({"endpoint": "https://ep.com/stale", "keys": {"p256dh": "a", "auth": "b"}})

        with patch.object(svc, "_send_one", side_effect=_gone_exc(404)):
            await svc.notify(title="Hi", body="World")

        assert "https://ep.com/stale" not in svc._subscriptions

    async def test_exception_without_response_does_not_prune(self, session_factory) -> None:
        """Non-WebPush exceptions (no response attr) must not trigger pruning."""
        svc = _make_svc(session_factory)
        await svc.subscribe_async({"endpoint": "https://ep.com/keep", "keys": {"p256dh": "a", "auth": "b"}})

        with patch.object(svc, "_send_one", side_effect=Exception("network timeout")):
            await svc.notify(title="Hi", body="World")

        assert "https://ep.com/keep" in svc._subscriptions

    async def test_500_response_does_not_prune(self, session_factory) -> None:
        svc = _make_svc(session_factory)
        await svc.subscribe_async({"endpoint": "https://ep.com/keep", "keys": {"p256dh": "a", "auth": "b"}})

        with patch.object(svc, "_send_one", side_effect=_gone_exc(500)):
            await svc.notify(title="Hi", body="World")

        assert "https://ep.com/keep" in svc._subscriptions

    async def test_prune_db_failure_is_best_effort(self, session_factory) -> None:
        """A DB error during prune must not break the notification path."""
        svc = _make_svc(session_factory)
        await svc.subscribe_async({"endpoint": "https://ep.com/stale", "keys": {"p256dh": "a", "auth": "b"}})

        with (
            patch.object(svc, "_send_one", side_effect=_gone_exc(410)),
            patch(
                "backend.persistence.database.serialized_write",
                side_effect=RuntimeError("DB down"),
            ),
        ):
            await svc.notify(title="Hi", body="World")

        # Cache was still pruned even though DB prune failed
        assert "https://ep.com/stale" not in svc._subscriptions
