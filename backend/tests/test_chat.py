"""Tests for the /api/chat conversational agent endpoint."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, store, ollama


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _seed_event():
    """Push a fake foreground event into the state store."""
    from app.schemas import WindowEvent

    return WindowEvent(
        type="foreground",
        hwnd="0xABCD",
        title="Inbox - user@company.com - Outlook",
        process_exe="OUTLOOK.EXE",
        pid=1234,
        timestamp=datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
    )


@pytest.mark.anyio
async def test_chat_requires_message(client):
    resp = await client.post("/api/chat", json={})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_chat_empty_message_rejected(client):
    resp = await client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_chat_basic_response_without_ollama(client):
    """When Ollama is unavailable, chat still returns a useful response using desktop context."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "what am I doing?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert isinstance(data["response"], str)
    assert len(data["response"]) > 0
    assert "desktop_context" in data


@pytest.mark.anyio
async def test_chat_with_ollama_returns_llm_response(client):
    """When Ollama is available, chat uses LLM to generate response."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock, return_value="You are reading emails in Outlook."):
        resp = await client.post("/api/chat", json={"message": "what am I doing?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "You are reading emails in Outlook."
    assert data["source"] == "ollama"


@pytest.mark.anyio
async def test_chat_action_intent_triggers_autonomy(client):
    """When user requests an action, chat triggers an autonomy run."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "draft a reply to this email", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("action_triggered") is True
    assert "run_id" in data


@pytest.mark.anyio
async def test_chat_action_not_triggered_when_disabled(client):
    """When allow_actions is false, chat does not trigger autonomy runs."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "draft a reply to this email", "allow_actions": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("action_triggered") is False


@pytest.mark.anyio
async def test_chat_includes_desktop_context_when_available(client):
    """Chat response includes current desktop context."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "what's on my screen?"})

    assert resp.status_code == 200
    data = resp.json()
    ctx = data.get("desktop_context")
    assert ctx is not None
    assert ctx["window_title"] == "Inbox - user@company.com - Outlook"
    assert ctx["process_exe"] == "OUTLOOK.EXE"


@pytest.mark.anyio
async def test_chat_without_desktop_context(client):
    """Chat works even when no desktop state is available."""
    # Clear state store
    await store.hydrate([], None, False, None)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "hello"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["desktop_context"] is None
    assert len(data["response"]) > 0


@pytest.mark.anyio
async def test_chat_ollama_error_falls_back_gracefully(client):
    """If Ollama errors out, chat still returns a useful response."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock, return_value=None):
        resp = await client.post("/api/chat", json={"message": "what am I doing?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "context"
    assert len(data["response"]) > 0
