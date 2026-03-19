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

from backend.app_factory import create_app
from backend.cli import cli
from backend.logging_config import _ConsoleNoiseFilter, setup_logging

# Default app instance for ``uvicorn backend.main:app``
app = create_app()

__all__ = ["_ConsoleNoiseFilter", "app", "cli", "create_app", "setup_logging"]

if __name__ == "__main__":
    cli()
