"""Action policy settings API — presets, rules, MCP configs, trust grants, export/import."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.events import DomainEvent, DomainEventKind
from backend.models.schemas.base import CamelModel
from backend.persistence.policy_repo import PolicyRepository
from backend.services.event_bus import EventBus

router = APIRouter(prefix="/settings/policy", tags=["policy"], route_class=DishkaRoute)
log = structlog.get_logger()


async def _notify_policy_changed(event_bus: EventBus) -> None:
    """Publish a policy_settings_changed event so running jobs reload policy."""
    await event_bus.publish(
        DomainEvent(
            event_id=DomainEvent.make_event_id(),
            job_id="",
            timestamp=datetime.now(UTC),
            kind=DomainEventKind.policy_settings_changed,
            payload={},
        )
    )


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PolicyConfigResponse(CamelModel):
    preset: str
    batch_window_seconds: float
    daily_budget_usd: float | None = None


class UpdatePresetRequest(CamelModel):
    preset: str = Field(pattern=r"^(autonomous|supervised|strict)$")


class UpdateConfigRequest(CamelModel):
    preset: str | None = Field(default=None, pattern=r"^(autonomous|supervised|strict)$")
    batch_window_seconds: float | None = None
    daily_budget_usd: float | None = None


class PathRuleRequest(CamelModel):
    path_pattern: str
    tier: str = Field(pattern=r"^(observe|checkpoint|gate)$")
    reason: str


class ActionRuleRequest(CamelModel):
    match_pattern: str
    tier: str = Field(pattern=r"^(observe|checkpoint|gate)$")
    reason: str


class CostRuleRequest(CamelModel):
    condition: str
    promote_to: str = Field(pattern=r"^(checkpoint|gate)$")
    reason: str
    threshold_value: float | None = None


class MCPServerRequest(CamelModel):
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    contained: bool = False
    reversible: bool = False
    trusted: bool = False
    tool_overrides: dict[str, dict[str, bool]] = Field(default_factory=dict)


class TrustGrantRequest(CamelModel):
    kinds: list[str]
    path_pattern: str | None = None
    excludes: list[str] = Field(default_factory=list)
    command_pattern: str | None = None
    mcp_server: str | None = None
    job_id: str | None = None
    expires_at: str | None = None
    reason: str = ""


class PathRuleResponse(CamelModel):
    id: str
    path_pattern: str
    tier: str
    reason: str
    created_at: str


class ActionRuleResponse(CamelModel):
    id: str
    match_pattern: str
    tier: str
    reason: str
    created_at: str


class CostRuleResponse(CamelModel):
    id: str
    condition: str
    promote_to: str
    threshold_value: float | None = None
    reason: str
    created_at: str


class TrustGrantResponse(CamelModel):
    id: str
    job_id: str | None = None
    kinds: list[str] = Field(default_factory=list)
    path_pattern: str | None = None
    excludes: list[str] = Field(default_factory=list)
    command_pattern: str | None = None
    mcp_server: str | None = None
    expires_at: str | None = None
    created_at: str
    reason: str = ""


class MCPServerResponse(CamelModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    contained: bool = False
    reversible: bool = False
    trusted: bool = False
    tool_overrides: dict[str, dict[str, bool]] = Field(default_factory=dict)
    created_at: str


class FullPolicyResponse(CamelModel):
    config: PolicyConfigResponse
    path_rules: list[PathRuleResponse] = Field(default_factory=list)
    action_rules: list[ActionRuleResponse] = Field(default_factory=list)
    cost_rules: list[CostRuleResponse] = Field(default_factory=list)
    mcp_servers: list[MCPServerResponse] = Field(default_factory=list)
    trust_grants: list[TrustGrantResponse] = Field(default_factory=list)


class PolicyExportResponse(CamelModel):
    version: int
    config: dict[str, Any]
    path_rules: list[dict[str, Any]]
    action_rules: list[dict[str, Any]]
    cost_rules: list[dict[str, Any]]
    mcp_servers: list[dict[str, Any]]
    trust_grants: list[dict[str, Any]]


class PolicyImportRequest(CamelModel):
    version: int = 1
    config: dict[str, Any] | None = None
    path_rules: list[dict[str, Any]] = Field(default_factory=list)
    action_rules: list[dict[str, Any]] = Field(default_factory=list)
    cost_rules: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    trust_grants: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Policy config
# ---------------------------------------------------------------------------

@router.get("", response_model=FullPolicyResponse)
async def get_policy(sf: FromDishka[async_sessionmaker[AsyncSession]]) -> FullPolicyResponse:
    async with sf() as session:
        repo = PolicyRepository(session)
        config = await repo.get_config()
        return FullPolicyResponse(
            config=PolicyConfigResponse(**config),
            path_rules=[PathRuleResponse(**r) for r in await repo.list_path_rules()],
            action_rules=[ActionRuleResponse(**r) for r in await repo.list_action_rules()],
            cost_rules=[CostRuleResponse(**r) for r in await repo.list_cost_rules()],
            mcp_servers=[MCPServerResponse(**r) for r in await repo.list_mcp_configs()],
            trust_grants=[TrustGrantResponse(**r) for r in await repo.list_trust_grants()],
        )


@router.put("/preset")
async def update_preset(
    body: UpdatePresetRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> PolicyConfigResponse:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.update_config(preset=body.preset)
        await session.commit()
    await _notify_policy_changed(event_bus)
    return PolicyConfigResponse(**result)


@router.put("/config")
async def update_config(
    body: UpdateConfigRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> PolicyConfigResponse:
    async with sf() as session:
        repo = PolicyRepository(session)
        updates = body.model_dump(exclude_none=True)
        result = await repo.update_config(**updates)
        await session.commit()
    await _notify_policy_changed(event_bus)
    return PolicyConfigResponse(**result)


# ---------------------------------------------------------------------------
# Path rules
# ---------------------------------------------------------------------------

@router.get("/path-rules")
async def list_path_rules(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> list[dict[str, Any]]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.list_path_rules()


@router.post("/path-rules")
async def create_path_rule(
    body: PathRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.create_path_rule(body.path_pattern, body.tier, body.reason)
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.put("/path-rules/{rule_id}")
async def update_path_rule(
    rule_id: str,
    body: PathRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.update_path_rule(
            rule_id, path_pattern=body.path_pattern, tier=body.tier, reason=body.reason
        )
        if result is None:
            raise HTTPException(404, "Path rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.delete("/path-rules/{rule_id}")
async def delete_path_rule(
    rule_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        deleted = await repo.delete_path_rule(rule_id)
        if not deleted:
            raise HTTPException(404, "Path rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Action rules
# ---------------------------------------------------------------------------

@router.get("/action-rules")
async def list_action_rules(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> list[dict[str, Any]]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.list_action_rules()


@router.post("/action-rules")
async def create_action_rule(
    body: ActionRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    try:
        re.compile(body.match_pattern)
    except re.error as exc:
        raise HTTPException(status_code=422, detail=f"Invalid regex: {exc}") from exc
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.create_action_rule(body.match_pattern, body.tier, body.reason)
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.put("/action-rules/{rule_id}")
async def update_action_rule(
    rule_id: str,
    body: ActionRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    try:
        re.compile(body.match_pattern)
    except re.error as exc:
        raise HTTPException(status_code=422, detail=f"Invalid regex: {exc}") from exc
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.update_action_rule(
            rule_id, match_pattern=body.match_pattern, tier=body.tier, reason=body.reason
        )
        if result is None:
            raise HTTPException(404, "Action rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.delete("/action-rules/{rule_id}")
async def delete_action_rule(
    rule_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        deleted = await repo.delete_action_rule(rule_id)
        if not deleted:
            raise HTTPException(404, "Action rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Cost rules
# ---------------------------------------------------------------------------

@router.get("/cost-rules")
async def list_cost_rules(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> list[dict[str, Any]]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.list_cost_rules()


@router.post("/cost-rules")
async def create_cost_rule(
    body: CostRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.create_cost_rule(
            body.condition, body.promote_to, body.reason, body.threshold_value
        )
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.put("/cost-rules/{rule_id}")
async def update_cost_rule(
    rule_id: str,
    body: CostRuleRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.update_cost_rule(
            rule_id,
            condition=body.condition,
            promote_to=body.promote_to,
            reason=body.reason,
            threshold_value=body.threshold_value,
        )
        if result is None:
            raise HTTPException(404, "Cost rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.delete("/cost-rules/{rule_id}")
async def delete_cost_rule(
    rule_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        deleted = await repo.delete_cost_rule(rule_id)
        if not deleted:
            raise HTTPException(404, "Cost rule not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# MCP server configs
# ---------------------------------------------------------------------------

@router.get("/mcp-servers")
async def list_mcp_servers(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> list[dict[str, Any]]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.list_mcp_configs()


@router.post("/mcp-servers")
async def create_mcp_server(
    body: MCPServerRequest,
    name: str | None = None,
    sf: FromDishka[async_sessionmaker[AsyncSession]] = None,
    event_bus: FromDishka[EventBus] = None,
) -> dict[str, Any]:
    # name comes from query param for POST
    if not name:
        raise HTTPException(400, "name query parameter required")
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.upsert_mcp_config(
            name,
            command=body.command,
            args=body.args,
            env=body.env,
            contained=body.contained,
            reversible=body.reversible,
            trusted=body.trusted,
            tool_overrides=body.tool_overrides,
        )
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.put("/mcp-servers/{name}")
async def update_mcp_server(
    name: str,
    body: MCPServerRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.upsert_mcp_config(
            name,
            command=body.command,
            args=body.args,
            env=body.env,
            contained=body.contained,
            reversible=body.reversible,
            trusted=body.trusted,
            tool_overrides=body.tool_overrides,
        )
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.delete("/mcp-servers/{name}")
async def delete_mcp_server(
    name: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        deleted = await repo.delete_mcp_config(name)
        if not deleted:
            raise HTTPException(404, "MCP server config not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Trust grants
# ---------------------------------------------------------------------------

@router.get("/trust-grants")
async def list_trust_grants(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> list[dict[str, Any]]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.list_trust_grants()


@router.post("/trust-grants")
async def create_trust_grant(
    body: TrustGrantRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        result = await repo.create_trust_grant(
            kinds=body.kinds,
            path_pattern=body.path_pattern,
            excludes=body.excludes,
            command_pattern=body.command_pattern,
            mcp_server=body.mcp_server,
            job_id=body.job_id,
            expires_at=body.expires_at,
            reason=body.reason,
        )
        await session.commit()
    await _notify_policy_changed(event_bus)
    return result


@router.delete("/trust-grants/{grant_id}")
async def delete_trust_grant(
    grant_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        deleted = await repo.delete_trust_grant(grant_id)
        if not deleted:
            raise HTTPException(404, "Trust grant not found")
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Export / Import (Phase 13)
# ---------------------------------------------------------------------------

@router.get("/export")
async def export_policy(
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> dict[str, Any]:
    async with sf() as session:
        repo = PolicyRepository(session)
        return await repo.export_all()


@router.post("/import")
async def import_policy(
    body: PolicyImportRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
    event_bus: FromDishka[EventBus],
) -> dict[str, str]:
    async with sf() as session:
        repo = PolicyRepository(session)
        try:
            await repo.import_all(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await session.commit()
    await _notify_policy_changed(event_bus)
    return {"status": "imported"}
