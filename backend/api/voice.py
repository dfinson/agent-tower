"""Voice transcription endpoint."""

from __future__ import annotations

import asyncio

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, UploadFile

from backend.di import VoiceMaxBytes
from backend.models.api_schemas import TranscribeResponse
from backend.services.voice_service import VoiceService

router = APIRouter(tags=["voice"], route_class=DishkaRoute)

ALLOWED_AUDIO_TYPES = frozenset({"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-wav"})

# Magic byte signatures for supported audio formats.
# Checked against the first bytes of the upload to prevent content-type spoofing.
_AUDIO_MAGIC: list[tuple[bytes, frozenset[str]]] = [
    (b"\x1a\x45\xdf\xa3", frozenset({"audio/webm"})),  # WebM / Matroska
    (b"OggS", frozenset({"audio/ogg"})),  # Ogg container
    (b"RIFF", frozenset({"audio/wav", "audio/x-wav"})),  # WAV (RIFF header)
    (b"\xff\xfb", frozenset({"audio/mpeg"})),  # MP3 frame sync
    (b"\xff\xf3", frozenset({"audio/mpeg"})),  # MP3 frame sync (MPEG2)
    (b"\xff\xf2", frozenset({"audio/mpeg"})),  # MP3 frame sync (MPEG2.5)
    (b"ID3", frozenset({"audio/mpeg"})),  # MP3 with ID3 tag
    (b"ftyp", frozenset({"audio/mp4"})),  # MP4 (ftyp at offset 4)
]

_AUDIO_READ_CHUNK = 64 * 1024  # 64 KB

_transcribe_semaphore = asyncio.Semaphore(2)


@router.post("/voice/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile,
    voice_service: FromDishka[VoiceService],
    max_bytes: FromDishka[VoiceMaxBytes],
) -> TranscribeResponse:
    """Upload audio, receive transcript."""
    # Validate content type (allow codec params like audio/webm;codecs=opus)
    if audio.content_type:
        base_type = audio.content_type.split(";")[0].strip()
        if base_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported audio format: {audio.content_type}")

    # Stream-read with early abort on size limit
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await audio.read(_AUDIO_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio exceeds {max_bytes // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Verify magic bytes match the declared content type to prevent spoofing
    if audio.content_type:
        base_type = audio.content_type.split(";")[0].strip()
        matched = False
        for magic, types in _AUDIO_MAGIC:
            if base_type in types:
                # MP4 ftyp is at offset 4
                if magic == b"ftyp":
                    matched = data[4:8] == magic if len(data) >= 8 else False
                else:
                    matched = data[: len(magic)] == magic
                if matched:
                    break
        if not matched:
            raise HTTPException(status_code=415, detail="Audio content does not match declared type")

    # Concurrency-limited, off-event-loop transcription
    if _transcribe_semaphore._value == 0:  # noqa: SLF001
        raise HTTPException(status_code=429, detail="Transcription busy, try again later")

    async with _transcribe_semaphore:
        text = await asyncio.to_thread(voice_service.transcribe, data)

    return TranscribeResponse(text=text)
