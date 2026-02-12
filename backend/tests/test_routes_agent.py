"""Tests for agent, vision, chat, and bridge routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")
os.environ.setdefault("CLASSIFIER_USE_OLLAMA", "0")
os.environ.setdefault("CLASSIFIER_DEFAULT", "docs")
os.environ.setdefault("UI_TELEMETRY_ARTIFACT_DIR", "/tmp/desktopai-ui-telemetry-test")

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_personality_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/personality")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_mode" in data
    assert "auto_adapt_enabled" in data
    assert "session_energy" in data
    assert "recommended_mode" in data
    assert "session_summary" in data


@pytest.mark.asyncio
async def test_bridge_status():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/agent/bridge")
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data


@pytest.mark.asyncio
async def test_vision_agent_run():
    """Vision agent run endpoint returns a run object."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/agent/run", json={
            "objective": "test objective",
            "max_iterations": 1,
        })
    # May return 200 (run started) or 503 (bridge/agent not available)
    assert resp.status_code in {200, 503}
    if resp.status_code == 200:
        data = resp.json()
        assert "run" in data


@pytest.mark.asyncio
async def test_chat_basic():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/chat", json={
            "message": "Hello",
            "allow_actions": False,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert "source" in data
    assert "conversation_id" in data


@pytest.mark.asyncio
async def test_chat_returns_conversation_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/chat", json={
            "message": "What am I working on?",
            "allow_actions": False,
        })
    data = resp.json()
    assert data["conversation_id"] is not None
    assert len(data["conversation_id"]) > 0


@pytest.mark.asyncio
async def test_chat_personality_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/chat", json={
            "message": "Hello operator",
            "allow_actions": False,
            "personality_mode": "operator",
        })
    data = resp.json()
    assert data["personality_mode"] == "operator"


@pytest.mark.asyncio
async def test_chat_conversation_persistence():
    """Sending with same conversation_id maintains context."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp1 = await ac.post("/api/chat", json={
            "message": "First message",
            "allow_actions": False,
        })
        conv_id = resp1.json()["conversation_id"]
        resp2 = await ac.post("/api/chat", json={
            "message": "Second message",
            "allow_actions": False,
            "conversation_id": conv_id,
        })
    assert resp2.json()["conversation_id"] == conv_id
