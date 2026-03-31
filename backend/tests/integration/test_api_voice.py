"""API integration tests for Voice transcription endpoint.

Tests exercise the POST /api/voice/transcribe route including
content-type validation, size limits, and error handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import Mock

    from httpx import AsyncClient


# ── Helpers ──────────────────────────────────────────────────────────


# WebM magic bytes prefix for realistic test data
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"


def _audio_file(
    data: bytes = _WEBM_MAGIC + b"\x00" * 124,
    content_type: str = "audio/webm",
    filename: str = "clip.webm",
) -> dict[str, tuple[str, bytes, str]]:
    """Return kwargs suitable for ``client.post(files=...)``."""
    return {"audio": (filename, data, content_type)}


# ── Transcribe ───────────────────────────────────────────────────────


class TestTranscribe:
    async def test_success(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/voice/transcribe",
            files=_audio_file(),
        )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hello world"

    async def test_invalid_content_type(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/voice/transcribe",
            files=_audio_file(content_type="text/plain"),
        )
        assert resp.status_code == 415

    async def test_empty_file(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/voice/transcribe",
            files=_audio_file(data=b""),
        )
        assert resp.status_code == 400

    async def test_transcribe_exception(self, mock_voice_service: Mock, client: AsyncClient) -> None:
        original_side = mock_voice_service.transcribe.side_effect
        mock_voice_service.transcribe.side_effect = RuntimeError("model crashed")
        try:
            # ASGITransport re-raises app exceptions by default
            with pytest.raises(RuntimeError, match="model crashed"):
                await client.post(
                    "/api/voice/transcribe",
                    files=_audio_file(),
                )
        finally:
            mock_voice_service.transcribe.side_effect = original_side


class TestVoiceSizeLimit:
    """Test file size enforcement with a small limit."""

    @pytest.fixture
    def voice_max_bytes_value(self) -> int:
        """Override the default 10 MB limit with 64 bytes."""
        return 64

    async def test_file_too_large(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/voice/transcribe",
            files=_audio_file(data=_WEBM_MAGIC + b"\x00" * 256),
        )
        assert resp.status_code == 413
