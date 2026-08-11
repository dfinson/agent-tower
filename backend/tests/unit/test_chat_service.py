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


class TestChatServiceMessages:
    @pytest.mark.asyncio
    async def test_add_message_returns_none_for_missing_chat(self):
        repo = _mock_repo()
        repo.get.return_value = None
        service = ChatService(repo)

        result = await service.add_message("missing", role="user", content="hi")

        assert result is None
        repo.add_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_message_persists_via_repo(self):
        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.add_message.side_effect = lambda message: message
        service = ChatService(repo)

        result = await service.add_message("c1", role="user", content="Let's think this through")

        assert result is not None
        assert result.chat_id == "c1"
        assert result.role == "user"
        assert result.content == "Let's think this through"
        repo.add_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_build_transcript_returns_none_for_missing_chat(self):
        repo = _mock_repo()
        repo.get.return_value = None
        service = ChatService(repo)

        result = await service.build_transcript("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_build_transcript_concatenates_in_order(self):
        from backend.models.domain import ChatMessage

        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = [
            ChatMessage(id="m1", chat_id="c1", role="user", content="first", created_at=None),  # type: ignore[arg-type]
            ChatMessage(id="m2", chat_id="c1", role="assistant", content="second", created_at=None),  # type: ignore[arg-type]
        ]
        service = ChatService(repo)

        transcript = await service.build_transcript("c1")

        assert transcript == "user: first\nassistant: second"

    @pytest.mark.asyncio
    async def test_build_transcript_empty_for_no_messages(self):
        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = []
        service = ChatService(repo)

        transcript = await service.build_transcript("c1")

        assert transcript == ""


class TestChatServiceLaunchJob:
    @pytest.mark.asyncio
    async def test_launch_job_returns_none_for_missing_chat(self):
        repo = _mock_repo()
        repo.get.return_value = None
        service = ChatService(repo)
        job_service = AsyncMock()

        result = await service.launch_job("missing", job_service, repo="/repos/test")

        assert result is None
        job_service.create_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_launch_job_seeds_prompt_from_transcript(self):
        from backend.models.domain import ChatMessage

        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = [
            ChatMessage(id="m1", chat_id="c1", role="user", content="do the thing", created_at=None),  # type: ignore[arg-type]
        ]
        service = ChatService(repo)
        job_service = AsyncMock()
        fake_job = object()
        job_service.create_job.return_value = fake_job

        result = await service.launch_job("c1", job_service, repo="/repos/test")

        assert result is fake_job
        job_service.create_job.assert_awaited_once()
        (spec,), _ = job_service.create_job.await_args
        assert spec.repo == "/repos/test"
        assert spec.prompt == "user: do the thing"

    @pytest.mark.asyncio
    async def test_launch_job_settles_null_project_id_from_repo(self):
        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id=None,
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = []
        service = ChatService(repo)
        job_service = AsyncMock()
        job_service.create_job.return_value = object()

        await service.launch_job("c1", job_service, repo="/repos/test")

        repo.set_project_id.assert_awaited_once_with("c1", "/repos/test")

    @pytest.mark.asyncio
    async def test_launch_job_does_not_resettle_existing_project_id(self):
        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id="proj-a",
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = []
        service = ChatService(repo)
        job_service = AsyncMock()
        job_service.create_job.return_value = object()

        await service.launch_job("c1", job_service, repo="/repos/test")

        repo.set_project_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_launch_job_twice_creates_two_independent_jobs(self):
        repo = _mock_repo()
        repo.get.return_value = Chat(
            id="c1",
            project_id="proj-a",
            title="Hi",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.list_messages.return_value = []
        service = ChatService(repo)
        job_service = AsyncMock()
        job_service.create_job.side_effect = [object(), object()]

        job_1 = await service.launch_job("c1", job_service, repo="/repos/test")
        job_2 = await service.launch_job("c1", job_service, repo="/repos/test")

        assert job_1 is not job_2
        assert job_service.create_job.await_count == 2

    @pytest.mark.asyncio
    async def test_launch_job_does_not_mutate_chat_status(self):
        """The Chat is repeatable/never consumed: launching a Job never
        changes its status, title, or otherwise transforms it (AC 2)."""
        repo = _mock_repo()
        chat = Chat(
            id="c1",
            project_id="proj-a",
            title="Original title",
            created_at=None,  # type: ignore[arg-type]
            last_message_at=None,  # type: ignore[arg-type]
            status="open",
        )
        repo.get.return_value = chat
        repo.list_messages.return_value = []
        service = ChatService(repo)
        job_service = AsyncMock()
        job_service.create_job.return_value = object()

        await service.launch_job("c1", job_service, repo="/repos/test")

        assert chat.status == "open"
        assert chat.title == "Original title"


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
