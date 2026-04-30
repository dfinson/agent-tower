"""Action policy persistence — config, rules, trust grants, MCP server configs."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update

from backend.models.db import (
    ActionRuleRow,
    CostRuleRow,
    MCPServerConfigRow,
    PathRuleRow,
    PolicyConfigRow,
    TrustGrantRow,
)
from backend.persistence.repository import BaseRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PolicyRepository(BaseRepository):
    """Database access for action policy configuration."""

    # --- Policy config (singleton) ---

    async def get_config(self) -> dict[str, Any]:
        result = await self._session.execute(select(PolicyConfigRow).where(PolicyConfigRow.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            return {"preset": "supervised", "batch_window_seconds": 5.0, "daily_budget_usd": None}
        return {
            "preset": row.preset,
            "batch_window_seconds": row.batch_window_seconds,
            "daily_budget_usd": row.daily_budget_usd,
        }

    async def update_config(self, **kwargs: Any) -> dict[str, Any]:
        allowed = {"preset", "batch_window_seconds", "daily_budget_usd"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get_config()
        await self._session.execute(
            update(PolicyConfigRow).where(PolicyConfigRow.id == 1).values(**updates)
        )
        return await self.get_config()

    # --- Path rules ---

    async def list_path_rules(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(PathRuleRow).order_by(PathRuleRow.created_at)
        )
        return [
            {"id": r.id, "path_pattern": r.path_pattern, "tier": r.tier,
             "reason": r.reason, "created_at": r.created_at}
            for r in result.scalars()
        ]

    async def create_path_rule(
        self, path_pattern: str, tier: str, reason: str
    ) -> dict[str, Any]:
        row = PathRuleRow(
            id=uuid.uuid4().hex,
            path_pattern=path_pattern,
            tier=tier,
            reason=reason,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._session.add(row)
        return {"id": row.id, "path_pattern": row.path_pattern, "tier": row.tier,
                "reason": row.reason, "created_at": row.created_at}

    async def update_path_rule(self, rule_id: str, **kwargs: Any) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(PathRuleRow).where(PathRuleRow.id == rule_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        for k in ("path_pattern", "tier", "reason"):
            if k in kwargs:
                setattr(row, k, kwargs[k])
        return {"id": row.id, "path_pattern": row.path_pattern, "tier": row.tier,
                "reason": row.reason, "created_at": row.created_at}

    async def delete_path_rule(self, rule_id: str) -> bool:
        result = await self._session.execute(
            delete(PathRuleRow).where(PathRuleRow.id == rule_id)
        )
        return result.rowcount > 0

    # --- Action rules ---

    async def list_action_rules(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(ActionRuleRow).order_by(ActionRuleRow.created_at)
        )
        return [
            {"id": r.id, "match_pattern": r.match_pattern, "tier": r.tier,
             "reason": r.reason, "created_at": r.created_at}
            for r in result.scalars()
        ]

    async def create_action_rule(
        self, match_pattern: str, tier: str, reason: str
    ) -> dict[str, Any]:
        row = ActionRuleRow(
            id=uuid.uuid4().hex,
            match_pattern=match_pattern,
            tier=tier,
            reason=reason,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._session.add(row)
        return {"id": row.id, "match_pattern": row.match_pattern, "tier": row.tier,
                "reason": row.reason, "created_at": row.created_at}

    async def update_action_rule(self, rule_id: str, **kwargs: Any) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(ActionRuleRow).where(ActionRuleRow.id == rule_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        for k in ("match_pattern", "tier", "reason"):
            if k in kwargs:
                setattr(row, k, kwargs[k])
        return {"id": row.id, "match_pattern": row.match_pattern, "tier": row.tier,
                "reason": row.reason, "created_at": row.created_at}

    async def delete_action_rule(self, rule_id: str) -> bool:
        result = await self._session.execute(
            delete(ActionRuleRow).where(ActionRuleRow.id == rule_id)
        )
        return result.rowcount > 0

    # --- Cost rules ---

    async def list_cost_rules(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(CostRuleRow).order_by(CostRuleRow.created_at)
        )
        return [
            {"id": r.id, "condition": r.condition, "promote_to": r.promote_to,
             "threshold_value": r.threshold_value, "reason": r.reason, "created_at": r.created_at}
            for r in result.scalars()
        ]

    async def create_cost_rule(
        self, condition: str, promote_to: str, reason: str, threshold_value: float | None = None
    ) -> dict[str, Any]:
        row = CostRuleRow(
            id=uuid.uuid4().hex,
            condition=condition,
            promote_to=promote_to,
            threshold_value=threshold_value,
            reason=reason,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._session.add(row)
        return {"id": row.id, "condition": row.condition, "promote_to": row.promote_to,
                "threshold_value": row.threshold_value, "reason": row.reason,
                "created_at": row.created_at}

    async def update_cost_rule(self, rule_id: str, **kwargs: Any) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(CostRuleRow).where(CostRuleRow.id == rule_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        for k in ("condition", "promote_to", "threshold_value", "reason"):
            if k in kwargs:
                setattr(row, k, kwargs[k])
        return {"id": row.id, "condition": row.condition, "promote_to": row.promote_to,
                "threshold_value": row.threshold_value, "reason": row.reason,
                "created_at": row.created_at}

    async def delete_cost_rule(self, rule_id: str) -> bool:
        result = await self._session.execute(
            delete(CostRuleRow).where(CostRuleRow.id == rule_id)
        )
        return result.rowcount > 0

    # --- MCP server configs ---

    async def list_mcp_configs(self) -> list[dict[str, Any]]:
        result = await self._session.execute(
            select(MCPServerConfigRow).order_by(MCPServerConfigRow.name)
        )
        return [_mcp_row_to_dict(r) for r in result.scalars()]

    async def get_mcp_config(self, name: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(MCPServerConfigRow).where(MCPServerConfigRow.name == name)
        )
        row = result.scalar_one_or_none()
        return _mcp_row_to_dict(row) if row else None

    async def upsert_mcp_config(self, name: str, **kwargs: Any) -> dict[str, Any]:
        result = await self._session.execute(
            select(MCPServerConfigRow).where(MCPServerConfigRow.name == name)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = MCPServerConfigRow(
                name=name,
                command=kwargs.get("command", ""),
                args_json=json.dumps(kwargs["args"]) if "args" in kwargs else None,
                env_json=json.dumps(kwargs["env"]) if "env" in kwargs else None,
                contained=kwargs.get("contained", False),
                reversible=kwargs.get("reversible", False),
                trusted=kwargs.get("trusted", False),
                tool_overrides_json=json.dumps(kwargs["tool_overrides"]) if "tool_overrides" in kwargs else None,
                created_at=datetime.now(UTC).isoformat(),
            )
            self._session.add(row)
        else:
            for k in ("command", "contained", "reversible", "trusted"):
                if k in kwargs:
                    setattr(row, k, kwargs[k])
            if "args" in kwargs:
                row.args_json = json.dumps(kwargs["args"])
            if "env" in kwargs:
                row.env_json = json.dumps(kwargs["env"])
            if "tool_overrides" in kwargs:
                row.tool_overrides_json = json.dumps(kwargs["tool_overrides"])
        return _mcp_row_to_dict(row)

    async def delete_mcp_config(self, name: str) -> bool:
        result = await self._session.execute(
            delete(MCPServerConfigRow).where(MCPServerConfigRow.name == name)
        )
        return result.rowcount > 0

    # --- Trust grants ---

    async def list_trust_grants(self, active_only: bool = True) -> list[dict[str, Any]]:
        stmt = select(TrustGrantRow).order_by(TrustGrantRow.created_at.desc())
        if active_only:
            now = datetime.now(UTC).isoformat()
            stmt = stmt.where(
                (TrustGrantRow.expires_at.is_(None)) | (TrustGrantRow.expires_at > now)
            )
        result = await self._session.execute(stmt)
        return [_grant_row_to_dict(r) for r in result.scalars()]

    async def create_trust_grant(self, **kwargs: Any) -> dict[str, Any]:
        row = TrustGrantRow(
            id=kwargs.get("id") or uuid.uuid4().hex,
            job_id=kwargs.get("job_id"),
            kinds_json=json.dumps(kwargs.get("kinds", [])),
            path_pattern=kwargs.get("path_pattern"),
            excludes_json=json.dumps(kwargs["excludes"]) if "excludes" in kwargs else None,
            command_pattern=kwargs.get("command_pattern"),
            mcp_server=kwargs.get("mcp_server"),
            expires_at=kwargs["expires_at"].isoformat() if kwargs.get("expires_at") else None,
            created_at=datetime.now(UTC).isoformat(),
            reason=kwargs.get("reason", ""),
        )
        self._session.add(row)
        return _grant_row_to_dict(row)

    async def delete_trust_grant(self, grant_id: str) -> bool:
        result = await self._session.execute(
            delete(TrustGrantRow).where(TrustGrantRow.id == grant_id)
        )
        return result.rowcount > 0

    # --- Export / Import ---

    async def export_all(self) -> dict[str, Any]:
        config = await self.get_config()
        return {
            "version": 1,
            "config": config,
            "path_rules": await self.list_path_rules(),
            "action_rules": await self.list_action_rules(),
            "cost_rules": await self.list_cost_rules(),
            "mcp_servers": await self.list_mcp_configs(),
            "trust_grants": await self.list_trust_grants(active_only=False),
        }

    async def import_all(self, data: dict[str, Any]) -> None:
        if "config" in data:
            await self.update_config(**data["config"])

        # Clear existing rules/grants before importing to avoid UNIQUE violations
        await self._session.execute(delete(PathRuleRow))
        await self._session.execute(delete(ActionRuleRow))
        await self._session.execute(delete(CostRuleRow))
        await self._session.execute(delete(TrustGrantRow))

        for rule in data.get("path_rules", []):
            await self.create_path_rule(rule["path_pattern"], rule["tier"], rule["reason"])
        for rule in data.get("action_rules", []):
            try:
                re.compile(rule["match_pattern"])
            except re.error as exc:
                raise ValueError(f"Invalid regex in action rule: {exc}") from exc
            await self.create_action_rule(rule["match_pattern"], rule["tier"], rule["reason"])
        for rule in data.get("cost_rules", []):
            await self.create_cost_rule(
                rule["condition"], rule["promote_to"], rule["reason"],
                rule.get("threshold_value"),
            )
        for srv in data.get("mcp_servers", []):
            await self.upsert_mcp_config(srv["name"], **srv)
        for grant in data.get("trust_grants", []):
            await self.create_trust_grant(**grant)


def _mcp_row_to_dict(row: MCPServerConfigRow) -> dict[str, Any]:
    return {
        "name": row.name,
        "command": row.command,
        "args": json.loads(row.args_json) if row.args_json else [],
        "env": json.loads(row.env_json) if row.env_json else {},
        "contained": row.contained,
        "reversible": row.reversible,
        "trusted": row.trusted,
        "tool_overrides": json.loads(row.tool_overrides_json) if row.tool_overrides_json else {},
        "created_at": row.created_at,
    }


def _grant_row_to_dict(row: TrustGrantRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "kinds": json.loads(row.kinds_json) if row.kinds_json else [],
        "path_pattern": row.path_pattern,
        "excludes": json.loads(row.excludes_json) if row.excludes_json else [],
        "command_pattern": row.command_pattern,
        "mcp_server": row.mcp_server,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "reason": row.reason,
    }
