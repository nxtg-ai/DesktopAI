"""Tests for security response headers."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from unittest.mock import patch

from app.auth import _SECURITY_HEADERS
from app.main import app
from fastapi.testclient import TestClient


def test_security_headers_on_health():
    """Public /api/health endpoint should include security headers."""
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    for header, expected in _SECURITY_HEADERS.items():
        assert resp.headers.get(header) == expected, f"Missing or wrong {header}"


def test_security_headers_on_api():
    """API endpoints should include security headers."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = ""
        mock_settings.rate_limit_per_minute = 60
        client = TestClient(app)
        resp = client.get("/api/state")
        assert resp.status_code == 200
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


def test_security_headers_on_401():
    """401 responses should also include security headers."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        mock_settings.rate_limit_per_minute = 60
        client = TestClient(app)
        resp = client.get("/api/state")
        assert resp.status_code == 401
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


def test_security_headers_on_429():
    """Rate-limited responses should include security headers."""
    from app.auth import _RateLimiter

    with patch("app.auth._rate_limiter", _RateLimiter(max_requests=1, window_seconds=60)):
        with patch("app.auth.settings") as mock_settings:
            mock_settings.api_token = ""
            mock_settings.rate_limit_per_minute = 1
            client = TestClient(app)
            # First request succeeds
            resp1 = client.get("/api/state")
            assert resp1.status_code == 200
            # Second triggers 429
            resp2 = client.get("/api/state")
            assert resp2.status_code == 429
            assert resp2.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp2.headers.get("X-Frame-Options") == "DENY"


def test_x_xss_protection_disabled():
    """X-XSS-Protection should be '0' (modern recommendation)."""
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("X-XSS-Protection") == "0"


def test_referrer_policy():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_permissions_policy():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"
