"""Tests for VoiceService — transcription and model loading."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.voice_service import VoiceService


class TestVoiceServiceInit:
    def test_default_model(self) -> None:
        svc = VoiceService()
        assert svc._model_name == "base.en"

    def test_uses_module_default_model(self) -> None:
        svc = VoiceService()
        assert svc._model_name == "base.en"


class TestModelLoading:
    @patch("backend.services.voice_service._import_whisper")
    def test_loads_model_once(self, mock_import: MagicMock) -> None:
        mock_cls = MagicMock()
        mock_import.return_value = mock_cls
        svc = VoiceService()
        svc._ensure_model()
        svc._ensure_model()  # Should not create a second instance
        mock_cls.assert_called_once()


class TestTranscribe:
    @patch("backend.services.voice_service._import_whisper")
    def test_transcribes_audio(self, mock_import: MagicMock) -> None:
        mock_segment = MagicMock()
        mock_segment.text = "hello world"
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())
        mock_cls = MagicMock(return_value=mock_model)
        mock_import.return_value = mock_cls

        svc = VoiceService()
        result = svc.transcribe(b"fake-audio-data")
        assert "hello world" in result

    @patch("backend.services.voice_service._import_whisper")
    def test_empty_segments_returns_empty(self, mock_import: MagicMock) -> None:
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())
        mock_cls = MagicMock(return_value=mock_model)
        mock_import.return_value = mock_cls

        svc = VoiceService()
        result = svc.transcribe(b"")
        assert result == ""
