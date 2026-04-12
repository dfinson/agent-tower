"""Port preview proxy — reverse-proxies local development servers through CodePlane.

Enables previewing agent-built web apps without exposing extra ports.
Routes: ``/api/preview/{port}/{path}``
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter(tags=["preview"])

log = structlog.get_logger()

# Shared httpx client — created lazily to avoid import-time side effects.
_client = None


def _get_client():  # noqa: ANN202
    global _client  # noqa: PLW0603
    if _client is None:
        import httpx

        _client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0))
    return _client


@router.api_route("/preview/{port:int}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
async def preview_proxy(port: int, path: str, request: Request) -> Response:
    """Reverse-proxy a request to a local development server."""
    if port < 1024 or port > 65535:
        return JSONResponse({"detail": f"Port {port} not allowed (must be 1024-65535)"}, status_code=400)

    upstream_url = f"http://127.0.0.1:{port}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Forward headers (except Host which must match upstream)
    forward_headers = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower not in ("host", "connection", "transfer-encoding"):
            forward_headers[key] = value

    try:
        client = _get_client()
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
        lower = key.lower()
        if lower not in ("transfer-encoding", "connection", "content-encoding", "content-length"):
            response_headers[key] = value

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
