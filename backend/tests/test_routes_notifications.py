"""Tests for notification routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_list_notifications_returns_list():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert "notifications" in data
    assert isinstance(data["notifications"], list)


@pytest.mark.asyncio
async def test_list_notifications_unread_only():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/notifications?unread_only=true")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["notifications"], list)


@pytest.mark.asyncio
async def test_list_notifications_with_limit():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/notifications?limit=5")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_notification_count():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/notifications/count")
    assert resp.status_code == 200
    data = resp.json()
    assert "unread_count" in data
    assert isinstance(data["unread_count"], int)


@pytest.mark.asyncio
async def test_mark_nonexistent_notification_read():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/notifications/nonexistent-id/read")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_notification():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/api/notifications/nonexistent-id")
    assert resp.status_code == 404
