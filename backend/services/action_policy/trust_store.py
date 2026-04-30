"""Trust store — scoped, time-limited permissions that bypass gate tier."""

from __future__ import annotations

import fnmatch
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.services.action_policy.classifier import Action

log = structlog.get_logger()


@dataclass
class TrustGrant:
    """In-memory representation of a trust grant."""

    id: str
    kinds: set[str]
    path_pattern: str | None = None
    excludes: list[str] = field(default_factory=list)
    command_pattern: str | None = None
    mcp_server: str | None = None
    job_id: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""


class TrustStore:
    """In-memory trust grant cache with DB persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._grants: dict[str, TrustGrant] = {}

    async def load(self) -> None:
        """Load active grants from DB into memory."""
        from backend.persistence.policy_repo import PolicyRepository

        async with self._session_factory() as session:
            repo = PolicyRepository(session)
            rows = await repo.list_trust_grants(active_only=True)

        self._grants.clear()
        now = datetime.now(UTC)
        for row in rows:
            expires = None
            if row.get("expires_at"):
                try:
                    expires = datetime.fromisoformat(row["expires_at"])
                except (ValueError, TypeError):
                    log.warning(
                        "trust_grant_invalid_expires_at",
                        grant_id=row["id"],
                        expires_at=row["expires_at"],
                    )
            if expires and expires < now:
                continue
            grant = TrustGrant(
                id=row["id"],
                kinds=set(row.get("kinds", [])),
                path_pattern=row.get("path_pattern"),
                excludes=row.get("excludes", []),
                command_pattern=row.get("command_pattern"),
                mcp_server=row.get("mcp_server"),
                job_id=row.get("job_id"),
                expires_at=expires,
                reason=row.get("reason", ""),
            )
            self._grants[grant.id] = grant

        log.debug("trust_store_loaded", count=len(self._grants))

    def covers(self, action: Action) -> bool:
        """Check if any active trust grant covers this action."""
        now = datetime.now(UTC)
        for grant in self._grants.values():
            if grant.expires_at and grant.expires_at < now:
                continue
            if _grant_matches(grant, action):
                return True
        return False

    async def create(
        self,
        *,
        kinds: set[str],
        path_pattern: str | None = None,
        excludes: list[str] | None = None,
        command_pattern: str | None = None,
        mcp_server: str | None = None,
        job_id: str | None = None,
        expires_at: datetime | None = None,
        reason: str = "",
    ) -> TrustGrant:
        """Create a trust grant, persist to DB and cache in memory."""
        from backend.persistence.policy_repo import PolicyRepository

        grant = TrustGrant(
            id=uuid.uuid4().hex,
            kinds=kinds,
            path_pattern=path_pattern,
            excludes=excludes or [],
            command_pattern=command_pattern,
            mcp_server=mcp_server,
            job_id=job_id,
            expires_at=expires_at,
            reason=reason,
        )

        async with self._session_factory() as session:
            repo = PolicyRepository(session)
            await repo.create_trust_grant(
                id=grant.id,
                kinds=list(grant.kinds),
                path_pattern=grant.path_pattern,
                excludes=grant.excludes,
                command_pattern=grant.command_pattern,
                mcp_server=grant.mcp_server,
                job_id=grant.job_id,
                expires_at=grant.expires_at,
                reason=grant.reason,
            )
            await session.commit()

        self._grants[grant.id] = grant
        log.info("trust_grant_created", grant_id=grant.id, kinds=list(kinds))
        return grant

    async def revoke(self, grant_id: str) -> bool:
        """Remove a trust grant from DB and memory."""
        from backend.persistence.policy_repo import PolicyRepository

        async with self._session_factory() as session:
            repo = PolicyRepository(session)
            deleted = await repo.delete_trust_grant(grant_id)
            await session.commit()

        self._grants.pop(grant_id, None)
        return deleted

    def list_active(self) -> list[TrustGrant]:
        """Return currently active grants."""
        now = datetime.now(UTC)
        return [
            g for g in self._grants.values()
            if not g.expires_at or g.expires_at >= now
        ]


def _grant_matches(grant: TrustGrant, action: Action) -> bool:
    """Check if a single grant covers the given action."""
    from backend.services.action_policy.classifier import ActionKind

    # Kind check
    kind_map = {
        ActionKind.file: "write",
        ActionKind.shell: "shell",
        ActionKind.mcp_tool: "mcp",
        ActionKind.sdk_tool: "sdk",
    }
    action_kind_str = kind_map.get(action.kind, "")
    if grant.kinds and action_kind_str not in grant.kinds:
        return False

    # Job scope
    if grant.job_id and grant.job_id != action.job_id:
        return False

    # Path pattern (for file actions)
    if grant.path_pattern:
        if not action.path or not fnmatch.fnmatch(action.path, grant.path_pattern):
            return False
        # Check excludes
        for exclude in grant.excludes:
            if fnmatch.fnmatch(action.path, exclude):
                return False

    # Command pattern (for shell actions)
    if grant.command_pattern:
        from backend.services.action_policy.classifier import _safe_regex_search

        if not action.command or not _safe_regex_search(grant.command_pattern, action.command):
            return False

    # MCP server scope
    if grant.mcp_server:
        if not action.mcp_server or grant.mcp_server != action.mcp_server:
            return False

    return True
