import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from unittest.mock import patch

from app.main import app
from fastapi.testclient import TestClient

# -- Dev mode: no API_TOKEN configured --

def test_dev_mode_no_token_allows_api():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = ""
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        resp = client.get("/api/state")
        assert resp.status_code == 200


# -- Auth enforced --

def test_missing_token_returns_401():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/state")
        assert resp.status_code == 401
        assert "error" in resp.json()


def test_wrong_token_returns_401():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/state", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401


def test_correct_token_allows_request():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/state", headers={"Authorization": "Bearer test-secret"})
        assert resp.status_code == 200


def test_health_always_accessible():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_static_root_not_protected():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200


def test_ws_auth_with_wrong_token():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        with client.websocket_connect("/ws?token=wrong"):
            pass  # pragma: no cover


def test_ws_auth_correct_token():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        with client.websocket_connect("/ws?token=test-secret") as ws:
            data = ws.receive_json()
            assert data["type"] == "snapshot"


# -- Additional auth edge cases --

def test_empty_bearer_token_returns_401():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/state", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401


def test_malformed_authorization_header_returns_401():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        # "Basic" instead of "Bearer"
        resp = client.get("/api/state", headers={"Authorization": "Basic test-secret"})
        assert resp.status_code == 401


def test_token_in_query_param_for_http_ignored():
    """HTTP endpoints use Authorization header, not query params."""
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        resp = client.get("/api/state?token=test-secret")
        assert resp.status_code == 401


def test_ingest_ws_auth_with_correct_token():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        with client.websocket_connect("/ingest?token=test-secret") as ws:
            # Send a minimal event and expect ack
            ws.send_json({
                "type": "foreground",
                "hwnd": "0x1",
                "title": "test",
                "process_exe": "test.exe",
                "pid": 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "source": "test",
            })
            data = ws.receive_json()
            assert data["status"] == "ok"


def test_ingest_ws_auth_with_wrong_token():
    with patch("app.auth.settings") as mock_settings:
        mock_settings.api_token = "test-secret"
        client = TestClient(app)
        with client.websocket_connect("/ingest?token=wrong"):
            pass  # pragma: no cover


# -- Rate limiting --

def test_rate_limiting_returns_429():
    """Verify that exceeding rate limit returns 429 with Retry-After header."""
    from app.auth import _RateLimiter

    limiter = _RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, _ = limiter.is_allowed("1.2.3.4")
        assert allowed

    allowed, retry_after = limiter.is_allowed("1.2.3.4")
    assert not allowed
    assert retry_after >= 1


def test_rate_limiting_per_ip():
    """Different IPs have independent limits."""
    from app.auth import _RateLimiter

    limiter = _RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.is_allowed("1.1.1.1")[0]
    assert limiter.is_allowed("1.1.1.1")[0]
    assert not limiter.is_allowed("1.1.1.1")[0]
    # Different IP still allowed
    assert limiter.is_allowed("2.2.2.2")[0]
