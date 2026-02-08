from __future__ import annotations

import hmac
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings

_PUBLIC_PATHS = frozenset({"/api/health"})


def _is_protected(path: str) -> bool:
    """Return True for paths that require auth when a token is configured."""
    if path in _PUBLIC_PATHS:
        return False
    return path.startswith("/api/") or path in ("/ingest", "/ws")


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = settings.api_token
        if not token:
            return await call_next(request)

        if not _is_protected(request.url.path):
            return await call_next(request)

        # WebSocket upgrades: token in query param
        if request.scope.get("type") == "websocket" or "upgrade" in request.headers.get("connection", "").lower():
            qs = parse_qs(request.url.query)
            provided = (qs.get("token") or [None])[0]
        else:
            auth_header = request.headers.get("authorization", "")
            provided = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else None

        if provided is None or not hmac.compare_digest(provided, token):
            return JSONResponse({"error": "invalid or missing API token"}, status_code=401)

        return await call_next(request)
