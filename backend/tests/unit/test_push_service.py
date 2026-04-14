"""Tests for PushService — Web Push subscription and notification delivery."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.push_service import PushService, PushSubscription


@pytest.fixture
def svc() -> PushService:
    return PushService(
        vapid_private_key="fake-priv",
        vapid_public_key="fake-pub",
        vapid_mailto="mailto:test@test.dev",
    )


class TestPushServiceSubscribe:
    def test_valid_subscription(self, svc: PushService) -> None:
        svc.subscribe(
            {
                "endpoint": "https://push.example.com/sub1",
                "keys": {"p256dh": "abc", "auth": "xyz"},
            }
        )
        assert len(svc._subscriptions) == 1

    def test_missing_endpoint(self, svc: PushService) -> None:
        svc.subscribe({"keys": {"p256dh": "a", "auth": "b"}})
        assert len(svc._subscriptions) == 0

    def test_empty_endpoint(self, svc: PushService) -> None:
        svc.subscribe({"endpoint": "", "keys": {"p256dh": "a", "auth": "b"}})
        assert len(svc._subscriptions) == 0

    def test_missing_p256dh(self, svc: PushService) -> None:
        svc.subscribe({"endpoint": "https://push.example.com/sub1", "keys": {"auth": "b"}})
        assert len(svc._subscriptions) == 0

    def test_missing_auth(self, svc: PushService) -> None:
        svc.subscribe({"endpoint": "https://push.example.com/sub1", "keys": {"p256dh": "a"}})
        assert len(svc._subscriptions) == 0

    def test_missing_keys(self, svc: PushService) -> None:
        svc.subscribe({"endpoint": "https://push.example.com/sub1"})
        assert len(svc._subscriptions) == 0

    def test_duplicate_endpoint_overwrites(self, svc: PushService) -> None:
        ep = "https://push.example.com/sub1"
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "a", "auth": "b"}})
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "new", "auth": "new"}})
        assert len(svc._subscriptions) == 1
        assert svc._subscriptions[ep].keys["p256dh"] == "new"


class TestPushServiceUnsubscribe:
    def test_remove_existing(self, svc: PushService) -> None:
        ep = "https://push.example.com/sub1"
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "a", "auth": "b"}})
        svc.unsubscribe(ep)
        assert len(svc._subscriptions) == 0

    def test_remove_nonexistent_is_noop(self, svc: PushService) -> None:
        svc.unsubscribe("https://no-such-endpoint.com/x")
        assert len(svc._subscriptions) == 0


class TestPushServicePublicKey:
    def test_returns_configured_key(self, svc: PushService) -> None:
        assert svc.public_key == "fake-pub"


class TestPushServiceNotify:
    @pytest.mark.asyncio
    async def test_no_subscribers_is_noop(self, svc: PushService) -> None:
        await svc.notify(title="Test", body="Nothing")  # Should not raise

    @pytest.mark.asyncio
    async def test_successful_notification(self, svc: PushService) -> None:
        svc.subscribe(
            {
                "endpoint": "https://push.example.com/sub1",
                "keys": {"p256dh": "a", "auth": "b"},
            }
        )
        with patch.object(svc, "_send_one") as mock_send:
            await svc.notify(title="Hi", body="World", tag="test", url="/jobs")
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_410_subscription_removed(self, svc: PushService) -> None:
        ep = "https://push.example.com/sub1"
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "a", "auth": "b"}})
        with patch.object(svc, "_send_one", side_effect=Exception("410 Gone")):
            await svc.notify(title="Hi", body="World")
        assert ep not in svc._subscriptions

    @pytest.mark.asyncio
    async def test_stale_404_subscription_removed(self, svc: PushService) -> None:
        ep = "https://push.example.com/sub1"
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "a", "auth": "b"}})
        with patch.object(svc, "_send_one", side_effect=Exception("404 Not Found")):
            await svc.notify(title="Hi", body="World")
        assert ep not in svc._subscriptions

    @pytest.mark.asyncio
    async def test_other_error_keeps_subscription(self, svc: PushService) -> None:
        ep = "https://push.example.com/sub1"
        svc.subscribe({"endpoint": ep, "keys": {"p256dh": "a", "auth": "b"}})
        with patch.object(svc, "_send_one", side_effect=Exception("500 Internal Server Error")):
            await svc.notify(title="Hi", body="World")
        assert ep in svc._subscriptions

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, svc: PushService) -> None:
        for i in range(3):
            svc.subscribe(
                {
                    "endpoint": f"https://push.example.com/sub{i}",
                    "keys": {"p256dh": "a", "auth": "b"},
                }
            )
        with patch.object(svc, "_send_one") as mock_send:
            await svc.notify(title="Hi", body="World")
            assert mock_send.call_count == 3


class TestPushServiceSendOne:
    def test_calls_webpush(self, svc: PushService) -> None:
        sub = PushSubscription(endpoint="https://ep.com/x", keys={"p256dh": "a", "auth": "b"})
        with patch("pywebpush.webpush") as mock_wp:
            svc._send_one(sub, '{"title":"t"}')
            mock_wp.assert_called_once_with(
                subscription_info={"endpoint": "https://ep.com/x", "keys": {"p256dh": "a", "auth": "b"}},
                data='{"title":"t"}',
                vapid_private_key="fake-priv",
                vapid_claims={"sub": "mailto:test@test.dev"},
            )
