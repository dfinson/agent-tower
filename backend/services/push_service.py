"""Web Push notification service.

Manages push subscriptions (in-memory) and sends notifications via the
Web Push protocol. Subscriptions are ephemeral — if the server restarts,
clients re-subscribe automatically via the service worker.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class PushSubscription:
    """A single Web Push subscription from a client."""

    endpoint: str
    keys: dict[str, str]  # {p256dh, auth}


class PushService:
    """Manages Web Push subscriptions and notification delivery."""

    def __init__(
        self,
        vapid_private_key: str,
        vapid_public_key: str,
        vapid_mailto: str = "mailto:noreply@codeplane.dev",
    ) -> None:
        self._vapid_private_key = vapid_private_key
        self._vapid_public_key = vapid_public_key
        self._vapid_mailto = vapid_mailto
        self._subscriptions: dict[str, PushSubscription] = {}  # keyed by endpoint

    @property
    def public_key(self) -> str:
        return self._vapid_public_key

    def subscribe(self, subscription_info: dict[str, Any]) -> None:
        """Register a push subscription."""
        endpoint = subscription_info.get("endpoint", "")
        keys = subscription_info.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            log.warning("push_subscribe_invalid", endpoint=endpoint[:50] if endpoint else "empty")
            return
        self._subscriptions[endpoint] = PushSubscription(endpoint=endpoint, keys=keys)
        log.info("push_subscribed", endpoint=endpoint[:50], total=len(self._subscriptions))

    def unsubscribe(self, endpoint: str) -> None:
        """Remove a push subscription."""
        removed = self._subscriptions.pop(endpoint, None)
        if removed:
            log.info("push_unsubscribed", endpoint=endpoint[:50], total=len(self._subscriptions))

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
                    log.debug("push_subscription_expired", endpoint=endpoint[:50])
                else:
                    log.warning("push_send_failed", endpoint=endpoint[:50], error=error_msg)

        for ep in stale:
            self._subscriptions.pop(ep, None)

    def _send_one(self, sub: PushSubscription, payload: str) -> None:
        """Synchronous push to a single subscription (runs in executor)."""
        from pywebpush import webpush

        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
            data=payload,
            vapid_private_key=self._vapid_private_key,
            vapid_claims={"sub": self._vapid_mailto},
        )
