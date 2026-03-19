"""Logging configuration for CodePlane.

Configures structlog + stdlib logging with rotating file handler and
console handler with noise filtering.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import structlog

_LOG_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_CONSOLE_NOISE_PREFIXES: tuple[str, ...] = (
    "alembic",
    "uvicorn.access",
    "uvicorn.error",
    "mcp.server.streamable_http_manager",
    "backend.services.sse_manager",
    "backend.services.voice_service",
    "backend.services.utility_session",
)


class _ConsoleNoiseFilter(logging.Filter):
    """Keep warnings/errors on console while suppressing chatty info logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not any(record.name.startswith(prefix) for prefix in _CONSOLE_NOISE_PREFIXES)


def setup_logging(log_file: str, console_level: str = "info") -> None:
    """Configure structlog + stdlib logging.

    Strategy
    --------
    * **File handler** — always at DEBUG verbosity so every log line is
      persisted.  Uses a rotating handler (10 MB × 5 backups).
    * **Stderr handler** — respects ``console_level`` from config (default
      info) so the terminal stays readable at runtime.
    * **structlog** — uses the same stdlib handlers so all structured context
      fields are serialised consistently.
    """
    log_path = Path(log_file).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    console_int = _LOG_LEVEL_MAP.get(console_level.lower(), logging.INFO)
    shared_processors: list[structlog.typing.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "logger", "event"],
                sort_keys=True,
            ),
        ],
    )
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
    )

    # File handler: DEBUG, rotating 10 MB × 5
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Stderr handler: configured level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_int)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(_ConsoleNoiseFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # let handlers decide what to suppress
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Suppress chatty third-party loggers from polluting the debug file
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
