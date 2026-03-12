"""FastAPI application factory and CLI entry point."""

from __future__ import annotations

import click
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import approvals, artifacts, events, health, jobs, settings, voice, workspace
from backend.config import init_config, load_config
from backend.persistence.database import run_migrations


def create_app(*, dev: bool = False) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Tower", version="0.1.0")

    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(approvals.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(workspace.router, prefix="/api")
    app.include_router(voice.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")

    return app


@click.group()
def cli() -> None:
    """Tower — control tower for coding agents."""


@cli.command()
@click.option("--host", default=None, help="Bind host (default: from config or 127.0.0.1)")
@click.option("--port", default=None, type=int, help="Bind port (default: from config or 8080)")
@click.option("--dev", is_flag=True, help="Enable development mode (CORS for localhost:5173)")
@click.option("--tunnel", is_flag=True, help="Start Dev Tunnel for remote access")
def up(host: str | None, port: int | None, dev: bool, tunnel: bool) -> None:
    """Start the Tower server."""
    config = load_config()
    host = host or config.server.host
    port = port or config.server.port

    # Run Alembic migrations before starting the server
    run_migrations()

    app = create_app(dev=dev)
    uvicorn.run(app, host=host, port=port)


@cli.command()
def init() -> None:
    """Create default configuration at ~/.tower/config.yaml."""
    import backend.config as _cfg

    if _cfg.DEFAULT_CONFIG_PATH.exists():
        click.echo(f"Configuration already exists at {_cfg.DEFAULT_CONFIG_PATH}")
        click.echo("Delete it first if you want to regenerate defaults.")
        return
    path = init_config()
    click.echo(f"Created default configuration at {path}")


@cli.command()
def version() -> None:
    """Print Tower version."""
    click.echo("tower 0.1.0")


if __name__ == "__main__":
    cli()
