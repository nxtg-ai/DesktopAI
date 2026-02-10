"""Authentication, rate-limiting, and security headers middleware."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings

_PUBLIC_PATHS = frozenset({"/api/health"})
_RATE_LIMIT_EXEMPT = frozenset({"/api/health"})

# Security headers applied to every HTTP response
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _is_protected(path: str) -> bool:
    """Return True for paths that require auth when a token is configured."""
    if path in _PUBLIC_PATHS:
        return False
    return path.startswith("/api/") or path in ("/ingest", "/ws")


class _RateLimiter:
    """Simple per-IP sliding-window rate limiter."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits[client_ip]
        # Prune expired entries
        self._hits[client_ip] = hits = [t for t in hits if t > cutoff]
        if len(hits) >= self._max:
            retry_after = int(hits[0] - cutoff) + 1
            return False, max(retry_after, 1)
        hits.append(now)
        return True, 0


_rate_limiter = _RateLimiter(max_requests=settings.rate_limit_per_minute)


def _add_security_headers(response):
    """Attach security headers to an HTTP response."""
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Rate limiting (skip for exempt paths and WebSocket upgrades)
        path = request.url.path
        is_ws = request.scope.get("type") == "websocket" or "upgrade" in request.headers.get("connection", "").lower()
        if not is_ws and path not in _RATE_LIMIT_EXEMPT:
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = _rate_limiter.is_allowed(client_ip)
            if not allowed:
                return _add_security_headers(JSONResponse(
                    {"error": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                ))

        # Token auth
        token = settings.api_token
        if not token:
            return _add_security_headers(await call_next(request))

        if not _is_protected(path):
            return _add_security_headers(await call_next(request))

        # WebSocket upgrades: token in query param
        if is_ws:
            qs = parse_qs(request.url.query)
            provided = (qs.get("token") or [None])[0]
        else:
            auth_header = request.headers.get("authorization", "")
            provided = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else None

        if provided is None or not hmac.compare_digest(provided, token):
            return _add_security_headers(
                JSONResponse({"error": "invalid or missing API token"}, status_code=401)
            )

        return _add_security_headers(await call_next(request))
