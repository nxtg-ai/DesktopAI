"""Tests for UI telemetry and runtime log routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

from datetime import datetime, timezone

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_post_ui_telemetry():
    payload = {
        "events": [
            {
                "kind": "page_view",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "test-session-1",
            }
        ]
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/ui-telemetry", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1


@pytest.mark.asyncio
async def test_post_ui_telemetry_empty_events():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/ui-telemetry", json={"events": []})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_ui_telemetry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/ui-telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)


@pytest.mark.asyncio
async def test_list_ui_telemetry_sessions():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/ui-telemetry/sessions")
    assert resp.status_code == 200
    assert "sessions" in resp.json()


@pytest.mark.asyncio
async def test_reset_ui_telemetry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/ui-telemetry/reset")
    assert resp.status_code == 200
    assert "cleared" in resp.json()


@pytest.mark.asyncio
async def test_list_runtime_logs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/runtime-logs")
    assert resp.status_code == 200
    assert "logs" in resp.json()


@pytest.mark.asyncio
async def test_list_runtime_logs_with_filters():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/runtime-logs", params={"level": "INFO", "limit": 10})
    assert resp.status_code == 200
    assert "logs" in resp.json()


@pytest.mark.asyncio
async def test_list_runtime_logs_invalid_since():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/runtime-logs", params={"since": "not-a-date"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_runtime_logs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/runtime-logs/reset")
    assert resp.status_code in {200, 429}
    if resp.status_code == 200:
        assert "cleared" in resp.json()


@pytest.mark.asyncio
async def test_correlate_runtime_logs_missing_session():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/runtime-logs/correlate", params={"session_id": ""})
    assert resp.status_code in {400, 429}
