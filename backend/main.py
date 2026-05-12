"""CodePlane entry point.

This module provides the ASGI ``app`` object (for uvicorn/gunicorn) and the
``cli`` Click group (for the ``cpl`` command).  All heavy lifting is delegated
to focused modules:

* ``app_factory`` — FastAPI creation, middleware, routes, SPA fallback
* ``lifespan`` — startup/shutdown, service wiring, background tasks
* ``logging_config`` — structlog + stdlib logging setup
* ``cli`` — Click commands (up, setup, doctor, version) and tunnel management
"""

from __future__ import annotations

from typing import Any

from backend.cli import cli
from backend.logging_config import ConsoleNoiseFilter, setup_logging


def create_app() -> Any:  # noqa: ANN401
    """Lazy wrapper so the CLI entry point doesn't require fastapi."""
    from backend.app_factory import create_app as _create_app

    return _create_app()


# Default app instance for ``uvicorn backend.main:app``
# Lazy — only materializes when the ASGI server accesses it.
class _LazyApp:
    """Defers FastAPI app creation until first attribute access."""

    _app: Any = None

    def __getattr__(self, name: str) -> Any:  # noqa: ANN204
        if _LazyApp._app is None:
            _LazyApp._app = create_app()
        return getattr(_LazyApp._app, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN002, ANN003, ANN204
        if _LazyApp._app is None:
            _LazyApp._app = create_app()
        return _LazyApp._app(*args, **kwargs)


app = _LazyApp()

__all__ = ["ConsoleNoiseFilter", "app", "cli", "create_app", "setup_logging"]

if __name__ == "__main__":
    cli()
