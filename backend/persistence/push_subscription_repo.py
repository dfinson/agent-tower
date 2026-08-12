"""Persistence for Web Push subscription endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from backend.models.db import PushSubscriptionRow
from backend.persistence.repository import BaseRepository


class PushSubscriptionRepository(BaseRepository):
    """Database access for push subscription endpoints."""

    async def list_all(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(PushSubscriptionRow))
        return [
            {"endpoint": r.endpoint, "keys": {"p256dh": r.p256dh, "auth": r.auth_key}}
            for r in result.scalars()
        ]

    async def upsert(self, endpoint: str, p256dh: str, auth_key: str) -> None:
        """Insert or update a subscription (endpoint is the natural idempotency key)."""
        now = datetime.now(UTC).isoformat()
        existing = await self._session.execute(
            select(PushSubscriptionRow).where(PushSubscriptionRow.endpoint == endpoint)
        )
        row = existing.scalar_one_or_none()
        if row is None:
            self._session.add(
                PushSubscriptionRow(
                    endpoint=endpoint,
                    p256dh=p256dh,
                    auth_key=auth_key,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.p256dh = p256dh
            row.auth_key = auth_key
            row.updated_at = now
        await self._session.flush()

    async def delete(self, endpoint: str) -> bool:
        result = await self._session.execute(
            delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint == endpoint)
        )
        return result.rowcount > 0  # type: ignore[union-attr]

    async def delete_many(self, endpoints: list[str]) -> int:
        if not endpoints:
            return 0
        result = await self._session.execute(
            delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint.in_(endpoints))
        )
        return result.rowcount  # type: ignore[union-attr]
