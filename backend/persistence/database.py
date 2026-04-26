"""Database engine, session management, and migration runner."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_codeplane_dir

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# SQLite busy_timeout: how long a connection waits for a locked database
# before raising OperationalError. 5000ms accommodates concurrent writers
# in WAL mode without excessive blocking.
_SQLITE_BUSY_TIMEOUT_MS = 5000

# SQLAlchemy connection pool sizing for the async SQLite engine.
# pool_size=10 connections handle typical concurrent request load;
# max_overflow=20 extra connections absorb burst traffic;
# pool_timeout=60s prevents requests from waiting indefinitely.
_POOL_SIZE = 10
_POOL_MAX_OVERFLOW = 20
_POOL_TIMEOUT_S = 60


def get_database_url(db_path: Path | None = None) -> str:
    """Build the async SQLite database URL."""
    path = db_path or (get_codeplane_dir() / "data.db")
    return f"sqlite+aiosqlite:///{path}"


def _set_sqlite_pragmas(dbapi_conn: Any, _connection_record: Any) -> None:
    """Enable WAL mode and foreign keys for every connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


def create_engine(db_path: Path | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine."""
    url = get_database_url(db_path)
    engine = create_async_engine(
        url, echo=False, pool_size=_POOL_SIZE, max_overflow=_POOL_MAX_OVERFLOW, pool_timeout=_POOL_TIMEOUT_S,
    )
    sa_event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session; rolls back on exception, always closes."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def run_migrations(db_path: Path | None = None) -> None:
    """Run Alembic migrations programmatically at startup."""
    get_codeplane_dir().mkdir(parents=True, exist_ok=True)

    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config()
    repo_root = Path(__file__).resolve().parents[2]
    alembic_cfg.set_main_option("script_location", str(repo_root / "alembic"))
    db_url = f"sqlite:///{db_path or (get_codeplane_dir() / 'data.db')}"
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    try:
        command.upgrade(alembic_cfg, "head")
    except command.util.CommandError as exc:  # type: ignore[attr-defined]  # alembic.command.util not typed
        if "Can't locate revision" in str(exc):
            import sqlite3

            import structlog

            log = structlog.get_logger()
            log.warning(
                "stale_alembic_revision",
                error=str(exc),
                action="stamping to head",
            )
            conn = sqlite3.connect(str(db_path or (get_codeplane_dir() / "data.db")))
            try:
                from alembic.script import ScriptDirectory

                script = ScriptDirectory.from_config(alembic_cfg)
                heads = script.get_heads()
                head_rev = heads[0] if heads else "head"
                conn.execute("UPDATE alembic_version SET version_num = ?", (head_rev,))
                conn.commit()
            finally:
                conn.close()
            command.upgrade(alembic_cfg, "head")
        else:
            raise
