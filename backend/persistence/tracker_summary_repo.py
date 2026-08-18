"""Persistence for the latest normalized state of each TrackerLink."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from backend.models.db import CredentialRow, TrackerLinkRow, TrackerSummaryRow
from backend.persistence.repository import BaseRepository

if TYPE_CHECKING:
    from backend.services.tracker_adapter import TrackerTicket


class TrackerSummaryRepository(BaseRepository):
    async def list_targets(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(TrackerLinkRow, CredentialRow)
            .join(CredentialRow, CredentialRow.id == TrackerLinkRow.credential_id)
            .order_by(TrackerLinkRow.created_at)
        )
        return [_target_to_dict(link, credential) for link, credential in result.all()]

    async def get_target(self, *, project_id: str, link_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(TrackerLinkRow, CredentialRow)
            .join(CredentialRow, CredentialRow.id == TrackerLinkRow.credential_id)
            .where(
                TrackerLinkRow.id == link_id,
                TrackerLinkRow.project_id == project_id,
            )
        )
        row = result.one_or_none()
        return _target_to_dict(*row) if row else None

    async def get_target_by_link_id(self, link_id: str) -> dict[str, Any] | None:
        """Resolve provider and credential context for one explicit TrackerLink."""
        result = await self._session.execute(
            select(TrackerLinkRow, CredentialRow)
            .join(CredentialRow, CredentialRow.id == TrackerLinkRow.credential_id)
            .where(TrackerLinkRow.id == link_id)
        )
        row = result.one_or_none()
        return _target_to_dict(*row) if row else None

    async def get(self, tracker_link_id: str) -> dict[str, Any] | None:
        row = await self._session.get(TrackerSummaryRow, tracker_link_id)
        return _summary_to_dict(row) if row else None

    async def list_for_project(self, project_id: str) -> dict[str, dict[str, Any]]:
        result = await self._session.execute(
            select(TrackerSummaryRow)
            .join(TrackerLinkRow, TrackerLinkRow.id == TrackerSummaryRow.tracker_link_id)
            .where(TrackerLinkRow.project_id == project_id)
        )
        return {row.tracker_link_id: _summary_to_dict(row) for row in result.scalars()}

    async def record_success(
        self,
        tracker_link_id: str,
        tickets: list[TrackerTicket],
    ) -> dict[str, Any]:
        row = await self._get_or_create(tracker_link_id)
        row.tickets_json = json.dumps([asdict(ticket) for ticket in tickets])
        row.last_synced_at = datetime.now(UTC).isoformat()
        row.last_error = None
        await self._session.flush()
        return _summary_to_dict(row)

    async def record_error(self, tracker_link_id: str, error: str) -> dict[str, Any]:
        row = await self._get_or_create(tracker_link_id)
        row.last_error = error
        await self._session.flush()
        return _summary_to_dict(row)

    async def _get_or_create(self, tracker_link_id: str) -> TrackerSummaryRow:
        row = await self._session.get(TrackerSummaryRow, tracker_link_id)
        if row is None:
            row = TrackerSummaryRow(
                tracker_link_id=tracker_link_id,
                tickets_json="[]",
                last_synced_at=None,
                last_error=None,
            )
            self._session.add(row)
        return row


def _target_to_dict(link: TrackerLinkRow, credential: CredentialRow) -> dict[str, Any]:
    return {
        "link_id": link.id,
        "project_id": link.project_id,
        "credential_id": link.credential_id,
        "external_ref": link.external_ref,
        "provider": credential.provider,
        "base_url": credential.base_url,
        "email": credential.email,
    }


def _summary_to_dict(row: TrackerSummaryRow) -> dict[str, Any]:
    try:
        tickets = json.loads(row.tickets_json)
    except (TypeError, json.JSONDecodeError):
        tickets = []
    return {
        "tracker_link_id": row.tracker_link_id,
        "tickets": tickets if isinstance(tickets, list) else [],
        "last_synced_at": row.last_synced_at,
        "last_error": row.last_error,
    }
