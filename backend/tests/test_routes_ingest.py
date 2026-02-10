"""Tests for ingest routes: POST /api/events."""

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
async def test_post_event_ok():
    payload = {
        "type": "foreground",
        "hwnd": "0xABC",
        "title": "Notepad",
        "process_exe": "notepad.exe",
        "pid": 42,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/events", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_post_event_missing_required_field():
    payload = {"type": "foreground"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/events", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_event_idle_type():
    payload = {
        "type": "idle",
        "hwnd": "0x0",
        "title": "",
        "process_exe": "",
        "pid": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
        "idle_ms": 5000,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/events", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_post_event_active_type():
    payload = {
        "type": "active",
        "hwnd": "0x0",
        "title": "",
        "process_exe": "",
        "pid": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "test",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/events", json=payload)
    assert resp.status_code == 200
