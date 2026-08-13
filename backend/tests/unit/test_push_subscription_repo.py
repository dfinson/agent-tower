"""Tests for PushSubscriptionRepository — persistence round-trips."""

from __future__ import annotations

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


@pytest.mark.asyncio
class TestPushServiceRestart:
    """Prove subscriptions survive a simulated server restart."""

    async def test_subscription_survives_new_service_instance(self, session_factory) -> None:
        from backend.services.sharing.push_service import PushService

        # First "server lifetime": subscribe
        svc1 = PushService(
            vapid_private_key="k1",
            vapid_public_key="k2",
            session_factory=session_factory,
        )
        await svc1.subscribe_async({"endpoint": "https://ep.com/persist", "keys": {"p256dh": "abc", "auth": "xyz"}})

        # Second "server lifetime": new instance loads from DB
        svc2 = PushService(
            vapid_private_key="k1",
            vapid_public_key="k2",
            session_factory=session_factory,
        )
        await svc2.load_from_db()
        assert "https://ep.com/persist" in svc2._subscriptions

    async def test_410_prunes_from_db(self, session_factory) -> None:
        from unittest.mock import patch

        from backend.services.sharing.push_service import PushService

        svc = PushService(
            vapid_private_key="k1",
            vapid_public_key="k2",
            session_factory=session_factory,
        )
        await svc.subscribe_async({"endpoint": "https://ep.com/stale", "keys": {"p256dh": "a", "auth": "b"}})

        with patch.object(svc, "_send_one", side_effect=Exception("410 Gone")):
            await svc.notify(title="Hi", body="World")

        assert "https://ep.com/stale" not in svc._subscriptions

        # Verify also removed from DB
        async with session_factory() as session:
            from backend.persistence.push_subscription_repo import PushSubscriptionRepository

            repo = PushSubscriptionRepository(session)
            rows = await repo.list_all()
            assert len(rows) == 0
