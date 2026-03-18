"""Local voice transcription via faster-whisper.

Requires the ``voice`` extra: ``pip install codeplane[voice]``.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = structlog.get_logger()

_MODEL_NAME = "base.en"


def _import_whisper() -> type:
    """Import faster-whisper at runtime, raising a clear error if missing."""
    try:
        from faster_whisper import WhisperModel as _Cls
    except ImportError as exc:
        raise ImportError(
            "faster-whisper is required for voice features. "
            "Install it with: pip install codeplane[voice]"
        ) from exc
    return _Cls


class VoiceService:
    """Transcribes audio using faster-whisper locally.

    The model is loaded once and reused across requests.
    """

    def __init__(self) -> None:
        self._model_name = _MODEL_NAME
        self._model: WhisperModel | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            WhisperModel = _import_whisper()
            logger.debug("voice_model_loading", model=self._model_name)
            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
            logger.debug("voice_model_loaded", model=self._model_name)
        return self._model

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe raw audio bytes and return the text."""
        model = self._ensure_model()
        segments, _ = model.transcribe(io.BytesIO(audio_bytes))
        return " ".join(seg.text.strip() for seg in segments)
