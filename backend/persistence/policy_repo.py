"""Action policy persistence — config (preset + batch window + USD ceilings) and MCP configs.

The hand-rolled path/action/cost rule tables and the pattern-trust grant table are
retired: the DECISION is delegated wholesale to ``traceforge.governance`` (rules,
protected paths, count/effect budget, reason-code trust all live in the separate
governance store). CodePlane keeps only the product settings it still owns — the
preset (which selects a TraceForge profile), the approval batch window, the
per-preset USD ceiling overlay (enforced natively by ``JobSpendCeilingAssessor``),
and the MCP server launch configs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update

from backend.models.db import MCPServerConfigRow, PolicyConfigRow
from backend.persistence.repository import BaseRepository


class PolicyRepository(BaseRepository):
    """Database access for action policy configuration."""

    # --- Policy config (singleton) ---

    async def get_config(self) -> dict[str, Any]:
        result = await self._session.execute(select(PolicyConfigRow).where(PolicyConfigRow.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            return {"preset": "supervised", "batch_window_seconds": 5.0}
        return {
            "preset": row.preset,
            "batch_window_seconds": row.batch_window_seconds,
        }

    async def update_config(self, **kwargs: Any) -> dict[str, Any]:
        allowed = {"preset", "batch_window_seconds"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return await self.get_config()
        await self._session.execute(update(PolicyConfigRow).where(PolicyConfigRow.id == 1).values(**updates))
        return await self.get_config()

    # --- Per-preset USD ceilings (native cost-ceiling overlay) ---

    async def get_usd_ceilings(self) -> dict[str, tuple[float | None, float | None]]:
        """Return ``{preset: (warn_usd, ceiling_usd)}`` operator overrides.

        Empty when unset — the governance decider then applies each profile's baked
        default ceiling. Malformed JSON degrades to empty rather than raising.
        """
        result = await self._session.execute(select(PolicyConfigRow).where(PolicyConfigRow.id == 1))
        row = result.scalar_one_or_none()
        if row is None or not row.usd_ceilings_json:
            return {}
        try:
            raw = json.loads(row.usd_ceilings_json)
        except (ValueError, TypeError):
            return {}
        out: dict[str, tuple[float | None, float | None]] = {}
        if isinstance(raw, dict):
            for preset, pair in raw.items():
                warn = _opt_float(pair.get("warn_usd")) if isinstance(pair, dict) else None
                ceiling = _opt_float(pair.get("ceiling_usd")) if isinstance(pair, dict) else None
                out[str(preset)] = (warn, ceiling)
        return out

    async def set_usd_ceilings(self, ceilings: dict[str, dict[str, float | None]]) -> dict[str, Any]:
        """Persist per-preset USD ceiling overrides on the singleton config row.

        ``ceilings`` maps a preset name to ``{"warn_usd": .., "ceiling_usd": ..}``;
        either value may be ``None`` (no line). Returns the stored mapping.
        """
        payload = json.dumps(ceilings) if ceilings else None
        await self._session.execute(
            update(PolicyConfigRow).where(PolicyConfigRow.id == 1).values(usd_ceilings_json=payload)
        )
        return {"usd_ceilings": ceilings}

    # --- MCP server configs ---

    async def list_mcp_configs(self) -> list[dict[str, Any]]:
        result = await self._session.execute(select(MCPServerConfigRow).order_by(MCPServerConfigRow.name))
        return [_mcp_row_to_dict(r) for r in result.scalars()]

    async def get_mcp_config(self, name: str) -> dict[str, Any] | None:
        result = await self._session.execute(select(MCPServerConfigRow).where(MCPServerConfigRow.name == name))
        row = result.scalar_one_or_none()
        return _mcp_row_to_dict(row) if row else None

    async def upsert_mcp_config(self, name: str, **kwargs: Any) -> dict[str, Any]:
        result = await self._session.execute(select(MCPServerConfigRow).where(MCPServerConfigRow.name == name))
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
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(delete(MCPServerConfigRow).where(MCPServerConfigRow.name == name)),
        )
        return result.rowcount > 0

    # --- Export / Import ---

    async def export_all(self) -> dict[str, Any]:
        config = await self.get_config()
        return {
            "version": 2,
            "config": config,
            "usd_ceilings": await self.get_usd_ceilings(),
            "mcp_servers": await self.list_mcp_configs(),
        }

    async def import_all(self, data: dict[str, Any]) -> None:
        if "config" in data:
            await self.update_config(**data["config"])
        if "usd_ceilings" in data:
            ceilings = {
                str(preset): {"warn_usd": _opt_float(pair[0]), "ceiling_usd": _opt_float(pair[1])}
                for preset, pair in dict(data["usd_ceilings"]).items()
            }
            await self.set_usd_ceilings(ceilings)
        for srv in data.get("mcp_servers", []):
            await self.upsert_mcp_config(srv["name"], **srv)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


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
