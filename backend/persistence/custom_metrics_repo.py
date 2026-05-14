"""Persistence for custom metrics and metrics chat."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.persistence.database import serialized_write


class CustomMetricsRepository:
    """CRUD for the custom_metrics table.

    Uses a session factory (not request-scoped session) because pinned
    metrics are evaluated outside request context on dashboard loads.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_all(self, *, status: str = "active") -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM custom_metrics
                    WHERE status = :status
                    ORDER BY position ASC, created_at ASC
                """),
                {"status": status},
            )
            return [dict(row._mapping) for row in result]

    async def list_for_job_panel(self) -> list[dict[str, Any]]:
        async with self._sf() as session:
            result = await session.execute(
                text("""
                    SELECT * FROM custom_metrics
                    WHERE pin_job_panel = 1 AND status = 'active'
                    ORDER BY position ASC
                """),
            )
            return [dict(row._mapping) for row in result]

    async def get(self, metric_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            result = await session.execute(
                text("SELECT * FROM custom_metrics WHERE id = :id"),
                {"id": metric_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("status", "active")
        data.setdefault("position", 0)

        if "viz_config_json" not in data and "viz_config" in data:
            data["viz_config_json"] = json.dumps(data.pop("viz_config"))

        columns = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())

        async with serialized_write(self._sf) as session:
            await session.execute(
                text(f"INSERT INTO custom_metrics ({columns}) VALUES ({placeholders})"),
                data,
            )
        return data

    async def update(self, metric_id: str, updates: dict[str, Any]) -> None:
        updates["updated_at"] = datetime.now(UTC).isoformat()
        if "viz_config" in updates:
            updates["viz_config_json"] = json.dumps(updates.pop("viz_config"))

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = metric_id

        async with serialized_write(self._sf) as session:
            await session.execute(
                text(f"UPDATE custom_metrics SET {set_clause} WHERE id = :id"),
                updates,
            )

    async def delete(self, metric_id: str) -> None:
        async with serialized_write(self._sf) as session:
            await session.execute(
                text("DELETE FROM custom_metrics WHERE id = :id"),
                {"id": metric_id},
            )


class MetricsChatRepository:
    """Persistence for metrics chat conversation summaries."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save_exchange(
        self,
        *,
        conversation_id: str,
        question: str,
        answer_summary: str,
        viz_data_json: str | None = None,
        sql_queries_json: str | None = None,
    ) -> None:
        """Save a condensed Q&A exchange (not full chat history)."""
        now = datetime.now(UTC).isoformat()
        async with serialized_write(self._sf) as session:
            # Save the question
            await session.execute(
                text("""
                    INSERT INTO metrics_chat_messages
                    (conversation_id, role, content, created_at)
                    VALUES (:cid, 'user', :content, :ts)
                """),
                {"cid": conversation_id, "content": question, "ts": now},
            )
            # Save the condensed answer
            await session.execute(
                text("""
                    INSERT INTO metrics_chat_messages
                    (conversation_id, role, content, condensed_summary,
                     viz_data_json, sql_queries_json, created_at)
                    VALUES (:cid, 'assistant', :content, :summary,
                            :viz, :sql, :ts)
                """),
                {
                    "cid": conversation_id,
                    "content": answer_summary,
                    "summary": answer_summary,
                    "viz": viz_data_json,
                    "sql": sql_queries_json,
                    "ts": now,
                },
            )

    async def get_conversation_summary(self, conversation_id: str) -> str:
        """Build a condensed summary of prior exchanges for context."""
        async with self._sf() as session:
            result = await session.execute(
                text("""
                    SELECT role, content, condensed_summary
                    FROM metrics_chat_messages
                    WHERE conversation_id = :cid
                    ORDER BY id ASC
                """),
                {"cid": conversation_id},
            )
            rows = result.mappings().all()

        parts: list[str] = []
        for row in rows:
            role = row["role"]
            summary = row["condensed_summary"] or row["content"]
            parts.append(f"{role}: {summary}")

        return "\n".join(parts[-20:])  # Last 10 exchanges max

    async def list_conversations(self) -> list[dict[str, Any]]:
        """List unique conversations with their latest message."""
        async with self._sf() as session:
            result = await session.execute(
                text("""
                    SELECT conversation_id,
                           MIN(created_at) as started_at,
                           MAX(created_at) as last_message_at,
                           COUNT(*) as message_count
                    FROM metrics_chat_messages
                    GROUP BY conversation_id
                    ORDER BY MAX(created_at) DESC
                """),
            )
            return [dict(row._mapping) for row in result]
