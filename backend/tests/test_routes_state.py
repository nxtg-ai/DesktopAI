"""Tests for state and snapshot routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from datetime import datetime, timezone

import pytest
from app.main import app, store
from app.schemas import WindowEvent
from httpx import ASGITransport, AsyncClient


def _make_event(**overrides):
    defaults = dict(
        type="foreground",
        timestamp=datetime.now(timezone.utc),
        title="Test Window",
        process_exe="test.exe",
        source="test",
        hwnd="0x1234",
    )
    defaults.update(overrides)
    return WindowEvent(**defaults)


@pytest.mark.asyncio
async def test_snapshot_no_context():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/state/snapshot")
    assert resp.status_code == 200
    assert resp.json()["context"] is None


@pytest.mark.asyncio
async def test_snapshot_with_event():
    event = _make_event(title="Outlook - Inbox", process_exe="outlook.exe")
    await store.record(event)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/state/snapshot")
    assert resp.status_code == 200
    ctx = resp.json()["context"]
    assert ctx is not None
    assert ctx["window_title"] == "Outlook - Inbox"
    assert ctx["process_exe"] == "outlook.exe"
    assert "timestamp" in ctx
    assert "screenshot_available" in ctx


@pytest.mark.asyncio
async def test_collector_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/collector")
    assert resp.status_code == 200
    data = resp.json()
    assert "ws_connected" in data
    assert "total_events" in data
