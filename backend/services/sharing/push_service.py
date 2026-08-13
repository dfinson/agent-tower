"""Web Push notification service.

Manages push subscriptions (persisted in the database) and sends notifications
via the Web Push protocol. On startup the service loads existing subscriptions
from the DB so they survive server restarts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = structlog.get_logger()


@dataclass
class PushSubscription:
    """A single Web Push subscription from a client."""

    endpoint: str
    keys: dict[str, str]  # {p256dh, auth}


class PushService:
    """Manages Web Push subscriptions and notification delivery.

    Subscriptions are persisted via PushSubscriptionRepository and cached
    in-memory for fast notification fanout.
    """

    def __init__(
        self,
        vapid_private_key: str,
        vapid_public_key: str,
        session_factory: async_sessionmaker | None = None,
        vapid_mailto: str = "mailto:noreply@codeplane.dev",
    ) -> None:
        self._vapid_private_key = vapid_private_key
        self._vapid_public_key = vapid_public_key
        self._vapid_mailto = vapid_mailto
        self._session_factory = session_factory
        self._subscriptions: dict[str, PushSubscription] = {}  # keyed by endpoint

    @property
    def public_key(self) -> str:
        return self._vapid_public_key

    async def load_from_db(self) -> None:
        """Load persisted subscriptions into memory. Call once at startup."""
        if self._session_factory is None:
            return
        from backend.persistence.push_subscription_repo import PushSubscriptionRepository

        async with self._session_factory() as session:
            repo = PushSubscriptionRepository(session)
            rows = await repo.list_all()
        for row in rows:
            self._subscriptions[row["endpoint"]] = PushSubscription(endpoint=row["endpoint"], keys=row["keys"])
        log.info("push_subscriptions_loaded", count=len(rows))

    def subscribe(self, subscription_info: dict[str, Any]) -> None:
        """Register a push subscription (cache only; use subscribe_async for persistence)."""
        endpoint = subscription_info.get("endpoint", "")
        keys = subscription_info.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            log.warning("push_subscribe_invalid", endpoint=endpoint if endpoint else "empty")
            return
        self._subscriptions[endpoint] = PushSubscription(endpoint=endpoint, keys=keys)
        log.info("push_subscribed", endpoint=endpoint, total=len(self._subscriptions))

    async def subscribe_async(self, subscription_info: dict[str, Any]) -> None:
        """Register a push subscription with DB persistence."""
        endpoint = subscription_info.get("endpoint", "")
        keys = subscription_info.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            log.warning("push_subscribe_invalid", endpoint=endpoint if endpoint else "empty")
            return
        self._subscriptions[endpoint] = PushSubscription(endpoint=endpoint, keys=keys)
        if self._session_factory is not None:
            from backend.persistence.push_subscription_repo import PushSubscriptionRepository

            async with self._session_factory() as session:
                repo = PushSubscriptionRepository(session)
                await repo.upsert(endpoint, keys["p256dh"], keys["auth"])
                await session.commit()
        log.info("push_subscribed", endpoint=endpoint, total=len(self._subscriptions))

    def unsubscribe(self, endpoint: str) -> None:
        """Remove a push subscription (cache only; use unsubscribe_async for persistence)."""
        removed = self._subscriptions.pop(endpoint, None)
        if removed:
            log.info("push_unsubscribed", endpoint=endpoint, total=len(self._subscriptions))

    async def unsubscribe_async(self, endpoint: str) -> None:
        """Remove a push subscription with DB persistence."""
        removed = self._subscriptions.pop(endpoint, None)
        if removed and self._session_factory is not None:
            from backend.persistence.push_subscription_repo import PushSubscriptionRepository

            async with self._session_factory() as session:
                repo = PushSubscriptionRepository(session)
                await repo.delete(endpoint)
                await session.commit()
            log.info("push_unsubscribed", endpoint=endpoint, total=len(self._subscriptions))

    async def notify(self, *, title: str, body: str, tag: str = "cpl", url: str = "/") -> None:
        """Send a push notification to all subscribers (fire-and-forget)."""
        if not self._subscriptions:
            return

        import json

        payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url})
        stale: list[str] = []

        for endpoint, sub in list(self._subscriptions.items()):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._send_one,
                    sub,
                    payload,
                )
            except Exception as exc:  # noqa: BLE001
                error_msg = str(exc)
                if "410" in error_msg or "404" in error_msg:
                    stale.append(endpoint)
                    log.debug("push_subscription_expired", endpoint=endpoint)
                else:
                    log.warning("push_send_failed", endpoint=endpoint, error=error_msg)

        for ep in stale:
            self._subscriptions.pop(ep, None)

        # Prune stale endpoints from the database
        if stale and self._session_factory is not None:
            from backend.persistence.push_subscription_repo import PushSubscriptionRepository

            async with self._session_factory() as session:
                repo = PushSubscriptionRepository(session)
                await repo.delete_many(stale)
                await session.commit()

    def _send_one(self, sub: PushSubscription, payload: str) -> None:
        """Synchronous push to a single subscription (runs in executor)."""
        from pywebpush import webpush  # type: ignore[import-untyped]

        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
            data=payload,
            vapid_private_key=self._vapid_private_key,
            vapid_claims={"sub": self._vapid_mailto},
        )
