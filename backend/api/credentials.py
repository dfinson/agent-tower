"""Global integration Credential API (Story 3.1, CAP-6/CAP-7).

Register once, in Settings > Integrations, independent of any Project
(AD-6). No route in this module ever returns a decrypted or encrypted
secret — list/get/create responses expose only provider/label/base_url/id/
created_at.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.schemas.base import CamelModel
from backend.persistence.credential_repo import CredentialReferencedError, CredentialRepository

router = APIRouter(prefix="/settings/credentials", tags=["credentials"], route_class=DishkaRoute)
log = structlog.get_logger()

_PROVIDER_PATTERN = r"^(github|jira|azure_devops)$"

# NFR9: per-provider PAT scope guidance, copy-paste only — never validated/enforced
# against TrackerLinks, since a Credential is deliberately global and reusable.
_PROVIDER_GUIDANCE: dict[str, str] = {
    "github": (
        "Use a fine-grained personal access token. Scope it to the repos you need: "
        "'Issues: Read & write' for tracker writes; add 'Contents: Read & write' + "
        "'Pull requests: Read & write' if PR creation will also be used. A scope broader "
        "than any single TrackerLink is expected, since this Credential may be attached "
        "to multiple Projects over time."
    ),
    "jira": (
        "Jira API tokens cannot be scoped down further than the full account — the token "
        "inherits every permission the account has. The codeplane_approval write-back gate, "
        "not token scope, is the real security boundary here."
    ),
    "azure_devops": (
        "Azure DevOps personal access tokens are organization-scoped, not project-scoped: "
        "scope to 'Work Items: Read & write' for tracker writes and 'Code: Read & write' for "
        "PR creation. One token covers every project in that org regardless of which project "
        "a TrackerLink references — again, the approval gate is the actual security boundary."
    ),
}


class CredentialResponse(CamelModel):
    id: str
    provider: str
    label: str
    base_url: str
    created_at: str


class CredentialListResponse(CamelModel):
    credentials: list[CredentialResponse] = Field(default_factory=list)


class CreateCredentialRequest(CamelModel):
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    label: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    pat: str = Field(min_length=1)


class ProviderGuidanceResponse(CamelModel):
    guidance: dict[str, str] = Field(default_factory=dict)


def _to_response(data: dict[str, Any]) -> CredentialResponse:
    return CredentialResponse(**data)


@router.get("", response_model=CredentialListResponse)
async def list_credentials(sf: FromDishka[async_sessionmaker[AsyncSession]]) -> CredentialListResponse:
    async with sf() as session:
        repo = CredentialRepository(session)
        rows = await repo.list_all()
    return CredentialListResponse(credentials=[_to_response(r) for r in rows])


@router.get("/guidance", response_model=ProviderGuidanceResponse)
async def get_provider_guidance() -> ProviderGuidanceResponse:
    """Return per-provider PAT scope guidance (NFR9). Static, no DB access."""
    return ProviderGuidanceResponse(guidance=_PROVIDER_GUIDANCE)


@router.post("", response_model=CredentialResponse, status_code=201)
async def create_credential(
    body: CreateCredentialRequest,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> CredentialResponse:
    credential_id = str(uuid.uuid4())
    async with sf() as session:
        repo = CredentialRepository(session)
        result = await repo.create(
            credential_id=credential_id,
            provider=body.provider,
            label=body.label,
            base_url=body.base_url,
            pat=body.pat,
        )
        await session.commit()
    # Never log the PAT itself — only non-secret identifying fields (NFR1).
    log.info("credential.created", credential_id=credential_id, provider=body.provider, label=body.label)
    return _to_response(result)


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: str,
    sf: FromDishka[async_sessionmaker[AsyncSession]],
) -> None:
    async with sf() as session:
        repo = CredentialRepository(session)
        try:
            deleted = await repo.delete(credential_id)
        except CredentialReferencedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Credential not found")
        await session.commit()
    log.info("credential.deleted", credential_id=credential_id)
