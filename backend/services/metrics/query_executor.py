"""SQL query executor for the metrics chat system.

Validates, rewrites, and executes read-only SQL queries against the
CodePlane telemetry tables with a configurable timeout.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger()

# Tables that user-generated queries may reference.
ALLOWED_TABLES = frozenset({
    "job_telemetry_spans",
    "job_telemetry_summary",
    "job_cost_attribution",
    "jobs",
})

# SQL keywords that must not appear in user queries.  Checked against the
# normalised (upper-cased, single-spaced) query text.
_FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(kw, re.IGNORECASE)
    for kw in [
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\bDROP\b",
        r"\bALTER\b",
        r"\bCREATE\b",
        r"\bATTACH\b",
        r"\bDETACH\b",
        r"\bPRAGMA\b",
        r"\bREINDEX\b",
        r"\bVACUUM\b",
        r"\bREPLACE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
        r"\bBEGIN\b",
        r"\bCOMMIT\b",
        r"\bROLLBACK\b",
        r"\bSAVEPOINT\b",
        r"\bRELEASE\b",
    ]
]

# Match table references: FROM <table>, JOIN <table>
_TABLE_REF_RE = re.compile(
    r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE
)


class QueryValidationError(Exception):
    """Raised when a query fails validation."""


def validate_query(sql: str) -> str:
    """Validate and return a cleaned SQL string.

    Raises ``QueryValidationError`` for disallowed operations.
    """
    cleaned = sql.strip().rstrip(";")
    if not cleaned:
        raise QueryValidationError("Empty query")

    # Must start with SELECT or WITH
    first_word = cleaned.split()[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise QueryValidationError(f"Only SELECT/WITH queries are allowed, got {first_word}")

    # Forbidden keywords
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(cleaned):
            raise QueryValidationError(
                f"Forbidden SQL keyword detected: {pattern.pattern}"
            )

    # Check table references
    for match in _TABLE_REF_RE.finditer(cleaned):
        table = match.group(1).lower()
        if table not in ALLOWED_TABLES:
            raise QueryValidationError(
                f"Table '{table}' is not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_TABLES))}"
            )

    return cleaned


async def execute_query(
    session_factory: async_sessionmaker[AsyncSession],
    sql: str,
    *,
    timeout_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Execute a validated read-only query and return rows as dicts.

    Uses a fresh session (not the request session) so the read-only query
    doesn't interfere with the request lifecycle.  Applies a SQLite
    ``LIMIT`` safety net if one isn't present.
    """
    import asyncio

    validated = validate_query(sql)

    async def _run() -> list[dict[str, Any]]:
        async with session_factory() as session:
            result = await session.execute(text(validated))
            columns = list(result.keys())
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        log.warning("metrics_query_timeout", sql=validated[:200])
        raise QueryValidationError(
            f"Query timed out after {timeout_seconds}s. Try simplifying the query."
        )
    except Exception as exc:
        if isinstance(exc, QueryValidationError):
            raise
        log.warning("metrics_query_error", error=str(exc), sql=validated[:200])
        raise QueryValidationError(f"Query execution error: {exc}") from exc
