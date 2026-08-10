"""Unit tests for backend.services.chat.chat_service — ChatService.

Also statically guards the AD-12/NFR8 invariant: chat_service.py must
never depend on GitService, structurally, not just behaviorally.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock

import pytest

from backend.models.domain import Chat
from backend.services.chat import chat_service as chat_service_module
from backend.services.chat.chat_service import ChatService


def _mock_repo() -> AsyncMock:
    repo = AsyncMock()

    async def _create(chat: Chat) -> Chat:
        return chat

    repo.create.side_effect = _create
    return repo


class TestChatServiceCreateChat:
    @pytest.mark.asyncio
    async def test_default_project_id_is_null(self):
        repo = _mock_repo()
        service = ChatService(repo)

        chat = await service.create_chat(title="Thinking something through")

        assert chat.project_id is None
        assert chat.title == "Thinking something through"
        assert chat.status == "open"
        repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_project_id_passed_through_when_provided(self):
        repo = _mock_repo()
        service = ChatService(repo)

        chat = await service.create_chat(title="Project-scoped chat", project_id="proj-123")

        assert chat.project_id == "proj-123"

    @pytest.mark.asyncio
    async def test_project_id_is_overridable_regardless_of_context(self):
        """Even when a caller supplies a project_id, it's just a normal
        argument — nothing in ChatService forces or coerces it."""
        repo = _mock_repo()
        service = ChatService(repo)

        chat_a = await service.create_chat(title="A", project_id="proj-a")
        chat_b = await service.create_chat(title="B", project_id=None)
        chat_c = await service.create_chat(title="C", project_id="proj-c")

        assert chat_a.project_id == "proj-a"
        assert chat_b.project_id is None
        assert chat_c.project_id == "proj-c"

    @pytest.mark.asyncio
    async def test_timestamps_set_on_creation(self):
        repo = _mock_repo()
        service = ChatService(repo)

        chat = await service.create_chat(title="Timed")

        assert chat.created_at is not None
        assert chat.last_message_at is not None
        assert chat.created_at == chat.last_message_at

    @pytest.mark.asyncio
    async def test_id_is_generated_and_unique(self):
        repo = _mock_repo()
        service = ChatService(repo)

        chat_1 = await service.create_chat(title="One")
        chat_2 = await service.create_chat(title="Two")

        assert chat_1.id
        assert chat_2.id
        assert chat_1.id != chat_2.id


class TestChatServiceReads:
    @pytest.mark.asyncio
    async def test_get_chat_delegates_to_repo(self):
        repo = _mock_repo()
        expected = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.get.return_value = expected
        service = ChatService(repo)

        result = await service.get_chat("c1")

        assert result is expected
        repo.get.assert_awaited_once_with("c1")

    @pytest.mark.asyncio
    async def test_list_chats_delegates_to_repo(self):
        repo = _mock_repo()
        repo.list_all.return_value = []
        service = ChatService(repo)

        result = await service.list_chats()

        assert result == []
        repo.list_all.assert_awaited_once()


class TestChatIsGitFree:
    """Structural guard for AD-12/NFR8: chat_service.py must have zero
    GitService dependency — not merely unused, but structurally absent.
    """

    def test_chat_service_module_never_imports_git_service(self):
        import ast

        source = inspect.getsource(chat_service_module)
        tree = ast.parse(source)
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
                imported_names.update(alias.name for alias in node.names)

        assert not any("git" in name.lower() for name in imported_names), imported_names
        assert not hasattr(chat_service_module, "GitService")

    def test_chat_service_class_has_no_git_attribute(self):
        repo = _mock_repo()
        service = ChatService(repo)
        for attr_name in dir(service):
            assert "git" not in attr_name.lower()
