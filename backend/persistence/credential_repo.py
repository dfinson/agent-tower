"""Persistence for global integration Credentials (Story 3.1, AD-6).

``CredentialRepository`` never returns a decrypted (or encrypted) secret from
list/get calls used by API responses — only ``resolve_secret`` decrypts, and
that method exists for future tracker-adapter use (Story 3.3+), not for any
Story 3.1 route.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import delete, select

from backend.models.db import CredentialRow, TrackerLinkRow
from backend.persistence.repository import BaseRepository
from backend.services.credentials.encryption import decrypt_secret, encrypt_secret

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult


class CredentialReferencedError(Exception):
    """Raised when deleting a Credential still referenced by a TrackerLink (AC2)."""


class CredentialRepository(BaseRepository):
    """Database access for global integration Credentials."""

    async def list_all(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(CredentialRow).order_by(CredentialRow.created_at))
        return [_row_to_dict(r) for r in result.scalars()]

    async def get(self, credential_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(select(CredentialRow).where(CredentialRow.id == credential_id))
        row = result.scalar_one_or_none()
        return _row_to_dict(row) if row else None

    async def create(self, *, credential_id: str, provider: str, label: str, base_url: str, pat: str) -> dict[str, Any]:
        row = CredentialRow(
            id=credential_id,
            provider=provider,
            label=label,
            base_url=base_url,
            encrypted_secret=encrypt_secret(pat),
            created_at=datetime.now(UTC).isoformat(),
        )
        self._session.add(row)
        await self._session.flush()
        return _row_to_dict(row)

    async def delete(self, credential_id: str) -> bool:
        """Delete a Credential, blocked while any TrackerLink still references it (AC2)."""
        ref_result = await self._session.execute(
            select(TrackerLinkRow.id).where(TrackerLinkRow.credential_id == credential_id).limit(1)
        )
        if ref_result.scalar_one_or_none() is not None:
            raise CredentialReferencedError(
                f"Credential {credential_id} is still referenced by one or more TrackerLinks"
            )
        result = await self._session.execute(delete(CredentialRow).where(CredentialRow.id == credential_id))
        return cast("CursorResult[Any]", result).rowcount > 0

    async def resolve_secret(self, credential_id: str) -> str | None:
        """Decrypt and return the PAT for server-side use only (never for API responses)."""
        result = await self._session.execute(select(CredentialRow).where(CredentialRow.id == credential_id))
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return decrypt_secret(row.encrypted_secret)


def _row_to_dict(row: CredentialRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "label": row.label,
        "base_url": row.base_url,
        "created_at": row.created_at,
    }
