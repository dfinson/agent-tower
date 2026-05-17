"""Sidecar template persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from backend.models.db import SidecarTemplateRow
from backend.models.domain import SidecarTemplate
from backend.persistence.repository import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime


class SidecarTemplateRepository(BaseRepository):
    """Database access for saved sidecar template records."""

    @staticmethod
    def _to_domain(row: SidecarTemplateRow) -> SidecarTemplate:
        return SidecarTemplate(
            id=row.id,
            name=row.name,
            description=row.description,
            definition_json=row.definition_json,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            enabled=row.enabled,
        )

    async def create(self, template: SidecarTemplate) -> SidecarTemplate:
        """Insert a new sidecar template."""
        row = SidecarTemplateRow(
            id=template.id,
            name=template.name,
            description=template.description,
            definition_json=template.definition_json,
            created_at=template.created_at,
            last_used_at=template.last_used_at,
            enabled=template.enabled,
        )
        self._session.add(row)
        await self._session.flush()
        return template

    async def get(self, template_id: str) -> SidecarTemplate | None:
        """Get a single template by ID."""
        stmt = select(SidecarTemplateRow).where(SidecarTemplateRow.id == template_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_name(self, name: str) -> SidecarTemplate | None:
        """Get a single template by unique name."""
        stmt = select(SidecarTemplateRow).where(SidecarTemplateRow.name == name)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[SidecarTemplate]:
        """List all saved templates, ordered by creation date descending."""
        stmt = select(SidecarTemplateRow).order_by(SidecarTemplateRow.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def list_enabled(self) -> list[SidecarTemplate]:
        """List only enabled templates, ordered by creation date descending."""
        stmt = (
            select(SidecarTemplateRow)
            .where(SidecarTemplateRow.enabled == True)  # noqa: E712
            .order_by(SidecarTemplateRow.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def update(
        self,
        template_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        definition_json: str | None = None,
        enabled: bool | None = None,
    ) -> SidecarTemplate | None:
        """Update a template's fields. Returns updated template or None."""
        values: dict[str, object] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if definition_json is not None:
            values["definition_json"] = definition_json
        if enabled is not None:
            values["enabled"] = enabled
        if not values:
            return await self.get(template_id)
        stmt = update(SidecarTemplateRow).where(SidecarTemplateRow.id == template_id).values(**values)
        await self._session.execute(stmt)
        await self._session.flush()
        return await self.get(template_id)

    async def touch_last_used(self, template_id: str, used_at: datetime) -> None:
        """Update the last_used_at timestamp."""
        stmt = update(SidecarTemplateRow).where(SidecarTemplateRow.id == template_id).values(last_used_at=used_at)
        await self._session.execute(stmt)
        await self._session.flush()

    async def delete(self, template_id: str) -> bool:
        """Delete a template. Returns True if a row was removed."""
        stmt = delete(SidecarTemplateRow).where(SidecarTemplateRow.id == template_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        rowcount = getattr(result, "rowcount", 0) or 0
        return rowcount > 0
