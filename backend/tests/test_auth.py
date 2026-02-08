import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


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
