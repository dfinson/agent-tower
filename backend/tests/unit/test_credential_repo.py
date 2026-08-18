"""Unit tests for CredentialRepository (Story 3.1, AD-6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.models.db import Base, TrackerLinkRow
from backend.persistence.credential_repo import CredentialReferencedError, CredentialRepository
from backend.persistence.database import _set_sqlite_pragmas
from backend.services.credentials import encryption

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_codeplane_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(encryption, "get_codeplane_dir", lambda: tmp_path)


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    sa_event.listen(eng.sync_engine, "connect", _set_sqlite_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


class TestCreateAndList:
    @pytest.mark.asyncio
    async def test_create_persists_encrypted_secret_not_plaintext(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        result = await repo.create(
            credential_id="cred-1",
            provider="github",
            label="My GitHub",
            base_url="https://api.github.com",
            pat="ghp_sentinel_secret_value",
        )
        await session.commit()

        assert result == {
            "id": "cred-1",
            "provider": "github",
            "label": "My GitHub",
            "base_url": "https://api.github.com",
            "email": None,
            "created_at": result["created_at"],
        }
        # No key in the returned dict ever carries the plaintext or the token.
        assert "pat" not in result
        assert "secret" not in result

    @pytest.mark.asyncio
    async def test_list_all_never_exposes_secret(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        await repo.create(
            credential_id="cred-1",
            provider="jira",
            label="Jira",
            base_url="https://x.atlassian.net",
            pat="tok",
            email="dev@example.com",
        )
        await session.commit()

        rows = await repo.list_all()
        assert len(rows) == 1
        assert "encrypted_secret" not in rows[0]
        assert "pat" not in rows[0]
        assert rows[0]["email"] == "dev@example.com"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_missing(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        assert await repo.get("does-not-exist") is None


class TestResolveSecret:
    @pytest.mark.asyncio
    async def test_resolve_secret_decrypts_original_pat(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        await repo.create(
            credential_id="cred-1", provider="github", label="GH", base_url="https://x", pat="my-real-pat"
        )
        await session.commit()

        assert await repo.resolve_secret("cred-1") == "my-real-pat"

    @pytest.mark.asyncio
    async def test_resolve_secret_returns_none_when_missing(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        assert await repo.resolve_secret("nope") is None


class TestUpdateJiraEmail:
    @pytest.mark.asyncio
    async def test_updates_only_jira_email_and_preserves_encrypted_token(
        self, session: AsyncSession
    ) -> None:
        repo = CredentialRepository(session)
        await repo.create(
            credential_id="legacy-jira",
            provider="jira",
            label="Legacy Jira",
            base_url="https://x.atlassian.net",
            pat="existing-secret",
            email=None,
        )
        await session.commit()

        updated = await repo.update_email("legacy-jira", "dev@example.com")
        await session.commit()

        assert updated is not None
        assert updated["email"] == "dev@example.com"
        assert "pat" not in updated
        assert await repo.resolve_secret("legacy-jira") == "existing-secret"

    @pytest.mark.asyncio
    async def test_rejects_email_update_for_non_jira_credential(
        self, session: AsyncSession
    ) -> None:
        repo = CredentialRepository(session)
        await repo.create(
            credential_id="github",
            provider="github",
            label="GitHub",
            base_url="https://api.github.com",
            pat="secret",
        )
        await session.commit()

        assert await repo.update_email("github", "dev@example.com") is None


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_succeeds_when_unreferenced(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        await repo.create(credential_id="cred-1", provider="github", label="GH", base_url="https://x", pat="p")
        await session.commit()

        assert await repo.delete("cred-1") is True
        assert await repo.get("cred-1") is None

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        assert await repo.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_blocked_while_referenced_by_tracker_link(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        await repo.create(credential_id="cred-1", provider="github", label="GH", base_url="https://x", pat="p")
        session.add(
            TrackerLinkRow(
                id="link-1",
                project_id="proj-1",
                credential_id="cred-1",
                external_ref="ORG/board",
                created_at="2026-01-01T00:00:00Z",
            )
        )
        await session.commit()

        with pytest.raises(CredentialReferencedError):
            await repo.delete("cred-1")

        # Still present after the blocked attempt.
        assert await repo.get("cred-1") is not None

    @pytest.mark.asyncio
    async def test_delete_succeeds_after_referencing_tracker_link_removed(self, session: AsyncSession) -> None:
        repo = CredentialRepository(session)
        await repo.create(credential_id="cred-1", provider="github", label="GH", base_url="https://x", pat="p")
        link = TrackerLinkRow(
            id="link-1",
            project_id="proj-1",
            credential_id="cred-1",
            external_ref="ORG/board",
            created_at="2026-01-01T00:00:00Z",
        )
        session.add(link)
        await session.commit()

        await session.delete(link)
        await session.commit()

        assert await repo.delete("cred-1") is True
