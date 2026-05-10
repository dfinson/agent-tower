"""OtelFileWatcher — async file tailer for Copilot OTEL JSONL exports.

Tails the file pointed to by COPILOT_OTEL_FILE_EXPORTER_PATH, parses
each JSONL line as an OTEL span, and routes it to IngestService.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backend.services.ingest_service import IngestService

log = structlog.get_logger()

_POLL_INTERVAL_S = 0.5


class OtelFileWatcher:
    """Tails COPILOT_OTEL_FILE_EXPORTER_PATH and routes spans to IngestService."""

    def __init__(self, path: str, ingest_service: IngestService) -> None:
        self._path = Path(path)
        self._ingest = ingest_service
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Begin tailing. Called from lifespan startup."""
        self._running = True
        self._task = asyncio.create_task(self._tail_loop(), name="otel-file-watcher")
        log.info("otel_file_watcher_started", path=str(self._path))

    async def stop(self) -> None:
        """Stop tailing. Called from lifespan shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("otel_file_watcher_stopped")

    async def _tail_loop(self) -> None:
        """Poll the JSONL file for new lines and process them."""
        # Seek to end on startup — don't replay history
        offset = 0
        if self._path.exists():
            offset = self._path.stat().st_size

        buffer = ""

        while self._running:
            try:
                if not self._path.exists():
                    await asyncio.sleep(_POLL_INTERVAL_S)
                    continue

                current_size = self._path.stat().st_size
                if current_size <= offset:
                    if current_size < offset:
                        # File was truncated — reset
                        offset = 0
                        buffer = ""
                    await asyncio.sleep(_POLL_INTERVAL_S)
                    continue

                # Read new bytes
                new_data = await asyncio.to_thread(self._read_from, offset)
                offset += len(new_data.encode())

                buffer += new_data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        span = json.loads(line)
                        await self._ingest.ingest_otel_span(span)
                    except json.JSONDecodeError:
                        log.debug("otel_invalid_json_line", line=line[:200])
                    except Exception:
                        log.debug("otel_span_processing_error", exc_info=True)

            except asyncio.CancelledError:
                return
            except Exception:
                log.debug("otel_watcher_error", exc_info=True)

            await asyncio.sleep(_POLL_INTERVAL_S)

    def _read_from(self, offset: int) -> str:
        """Read file from offset (called in thread)."""
        with open(self._path, encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            return f.read()
