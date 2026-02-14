"""Tests for the /api/chat conversational agent endpoint."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.main import app, chat_memory, ollama, store
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def _reset_store():
    """Clear state store between tests so seeded events don't leak."""
    await store.hydrate([], None, False, None)
    yield
    await store.hydrate([], None, False, None)


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


@pytest.mark.anyio
async def test_chat_returns_conversation_id(client):
    """Chat response always includes a conversation_id."""
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "hello"})
    data = resp.json()
    assert "conversation_id" in data
    assert isinstance(data["conversation_id"], str)
    assert len(data["conversation_id"]) == 36


@pytest.mark.anyio
async def test_chat_with_existing_conversation_id(client):
    """Chat preserves conversation_id when provided."""
    cid = await chat_memory.create_conversation("test")
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat", json={"message": "hello", "conversation_id": cid}
        )
    data = resp.json()
    assert data["conversation_id"] == cid


@pytest.mark.anyio
async def test_chat_multi_turn_context(client):
    """Multi-turn chat passes history to ollama."""
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock, return_value="First response") as mock_chat:
        resp1 = await client.post("/api/chat", json={"message": "first message"})
    cid = resp1.json()["conversation_id"]

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock, return_value="Second response") as mock_chat:
        resp2 = await client.post(
            "/api/chat", json={"message": "follow up", "conversation_id": cid}
        )
    # The second call should include history in messages
    call_args = mock_chat.call_args[0][0]
    # Should have system + history (user+assistant) + new user = at least 4 messages
    assert len(call_args) >= 4
    assert resp2.json()["conversation_id"] == cid


@pytest.mark.anyio
async def test_chat_new_conversation_created(client):
    """Each chat without conversation_id creates a new conversation."""
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp1 = await client.post("/api/chat", json={"message": "hello"})
        resp2 = await client.post("/api/chat", json={"message": "world"})

    cid1 = resp1.json()["conversation_id"]
    cid2 = resp2.json()["conversation_id"]
    assert cid1 != cid2


@pytest.mark.anyio
async def test_chat_includes_screenshot_when_available(client):
    """Chat response includes screenshot_b64 when desktop event has one."""
    from app.schemas import WindowEvent

    event = WindowEvent(
        type="foreground",
        hwnd="0x1234",
        title="Document.docx - Word",
        process_exe="WINWORD.EXE",
        pid=5678,
        timestamp=datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="test",
        screenshot_b64="aW1hZ2VkYXRh",  # base64 of "imagedata"
    )
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "what do you see?"})

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("screenshot_b64") == "aW1hZ2VkYXRh"
    assert data["desktop_context"]["screenshot_available"] is True


@pytest.mark.anyio
async def test_chat_omits_screenshot_when_unavailable(client):
    """Chat response does not include screenshot_b64 when not present."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "hello"})

    assert resp.status_code == 200
    data = resp.json()
    assert "screenshot_b64" not in data


@pytest.mark.anyio
async def test_chat_scroll_triggers_action(client):
    """'scroll down' should be detected as an action intent."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "scroll down in Notepad", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("action_triggered") is True


def test_personality_prompts_copilot_concise():
    """Copilot prompt should instruct brevity."""
    from app.routes.agent import _PERSONALITY_PROMPTS

    prompt = _PERSONALITY_PROMPTS["copilot"]
    assert "concise" in prompt.lower()
    assert "bullet" in prompt.lower()


def test_personality_prompts_operator_no_greetings():
    """Operator prompt should forbid greetings and pleasantries."""
    from app.routes.agent import _PERSONALITY_PROMPTS

    prompt = _PERSONALITY_PROMPTS["operator"]
    assert "pleasantries" in prompt.lower()
    assert "imperative" in prompt.lower()


@pytest.mark.anyio
async def test_chat_system_prompt_includes_recent_apps(client):
    """LLM system prompt should include recent app transitions."""
    from app.schemas import WindowEvent

    # Seed two events: user was in Notepad, then switched to browser
    e1 = WindowEvent(
        type="foreground", hwnd="0x1", title="Untitled - Notepad",
        process_exe="notepad.exe", pid=100,
        timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    e2 = WindowEvent(
        type="foreground", hwnd="0x2", title="DesktopAI Live Context",
        process_exe="chrome.exe", pid=200,
        timestamp=datetime(2025, 1, 1, 0, 1, 0, tzinfo=timezone.utc),
    )
    await store.record(e1)
    await store.record(e2)

    captured_messages = []

    async def mock_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return "I can see your apps."

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", side_effect=mock_chat):
        resp = await client.post("/api/chat", json={"message": "what am I doing?"})

    assert resp.status_code == 200
    # Check that the system prompt mentions notepad
    system_msgs = [m for m in captured_messages if m.get("role") == "system"]
    assert len(system_msgs) >= 1
    system_text = system_msgs[0]["content"].lower()
    assert "notepad" in system_text
