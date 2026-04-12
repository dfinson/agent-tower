"""Ephemeral share-token service for read-only job sharing.

Tokens are stored in-memory and expire after a configurable TTL.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24 hours


@dataclass
class ShareToken:
    token: str
    job_id: str
    created_at: float
    ttl: float


class ShareService:
    """In-memory store for share tokens."""

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self._tokens: dict[str, ShareToken] = {}
        self._ttl = ttl

    def create_token(self, job_id: str) -> ShareToken:
        """Generate a new share token for *job_id*."""
        self._evict_expired()
        token = secrets.token_urlsafe(32)
        entry = ShareToken(
            token=token,
            job_id=job_id,
            created_at=time.monotonic(),
            ttl=self._ttl,
        )
        self._tokens[token] = entry
        log.info("share_token_created", job_id=job_id, token=token[:8])
        return entry

    def validate(self, token: str) -> str | None:
        """Return the *job_id* if the token is valid, else ``None``."""
        entry = self._tokens.get(token)
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > entry.ttl:
            del self._tokens[token]
            return None
        return entry.job_id

    def revoke(self, token: str) -> bool:
        """Revoke a share token.  Returns ``True`` if it existed."""
        return self._tokens.pop(token, None) is not None

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._tokens.items() if now - v.created_at > v.ttl]
        for k in expired:
            del self._tokens[k]
