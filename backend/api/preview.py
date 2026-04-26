"""Port preview proxy — reverse-proxies local development servers through CodePlane.

Enables previewing agent-built web apps without exposing extra ports.
Routes: ``/api/preview/{port}/{path}``
"""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from backend.di import PreviewHttpClient

router = APIRouter(tags=["preview"], route_class=DishkaRoute)

log = structlog.get_logger()

_MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MB cap on proxied responses

_UPSTREAM_BASE = "http://127.0.0.1"

# Headers that MUST NOT be forwarded to upstream (hop-by-hop + spoofable).
_BLOCKED_REQUEST_HEADERS = frozenset(
    {
        "host",
        "connection",
        "transfer-encoding",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-real-ip",
        "forwarded",
    }
)

# Response headers stripped before forwarding back to the client.
_BLOCKED_RESPONSE_HEADERS = frozenset(
    {"transfer-encoding", "connection", "content-encoding", "content-length"}
)

@router.api_route("/preview/{port:int}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
async def preview_proxy(port: int, path: str, request: Request, client: FromDishka[PreviewHttpClient]) -> Response:
    """Reverse-proxy a request to a local development server."""
    if port < 1024 or port > 65535:
        return JSONResponse({"detail": f"Port {port} not allowed (must be 1024-65535)"}, status_code=400)

    upstream_url = f"{_UPSTREAM_BASE}:{port}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Forward headers (except blocked ones)
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() not in _BLOCKED_REQUEST_HEADERS:
            forward_headers[key] = value

    try:
        body = await request.body()
        upstream_response = await client.request(
            method=request.method,
            url=upstream_url,
            headers=forward_headers,
            content=body if body else None,
        )
    except Exception as exc:
        error_type = type(exc).__name__
        log.debug("preview_proxy_error", port=port, path=path, error=error_type)
        return JSONResponse(
            {"detail": f"Cannot connect to service on port {port}", "error": error_type},
            status_code=502,
        )

    # Forward response headers (skip hop-by-hop)
    response_headers = {}
    for key, value in upstream_response.headers.items():
        if key.lower() not in _BLOCKED_RESPONSE_HEADERS:
            response_headers[key] = value

    content = upstream_response.content
    if len(content) > _MAX_RESPONSE_BYTES:
        return JSONResponse(
            {"detail": f"Upstream response too large ({len(content)} bytes, limit {_MAX_RESPONSE_BYTES})"},
            status_code=502,
        )

    return Response(
        content=content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
