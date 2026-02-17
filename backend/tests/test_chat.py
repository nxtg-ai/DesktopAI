"""Tests for the /api/chat conversational agent endpoint."""

import json
import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app, autonomy, bridge, chat_memory, ollama, store, vision_runner
from app.recipes import Recipe, recipe_to_plan_steps
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


# ── Direct bridge command fast path tests ────────────────────────────────


def _mock_bridge_connected():
    """Context manager that makes bridge appear connected with a mock execute."""
    mock_exec = AsyncMock(return_value={"status": "ok"})
    return patch.object(bridge, "_ws", new=MagicMock()), \
           patch.object(bridge, "execute", mock_exec), \
           mock_exec


@pytest.mark.anyio
async def test_direct_open_application(client):
    """'open notepad' with bridge connected should execute directly, no run_id."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "open notepad", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data.get("run_id") is None  # direct, not async
    assert data["source"] == "direct"
    assert "open application" in data["response"].lower()
    mock_exec.assert_called_once_with(
        "open_application", {"application": "notepad"}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_focus_window(client):
    """'switch to Chrome' should call focus_window via bridge."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "switch to Chrome", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data.get("run_id") is None
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "focus_window", {"title": "Chrome"}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_type_in_window(client):
    """'type hello in Notepad' should focus then type (two bridge calls)."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "type hello in Notepad", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["source"] == "direct"
    assert "notepad" in data["response"].lower()
    assert mock_exec.call_count == 2
    mock_exec.assert_any_call("focus_window", {"title": "Notepad"}, timeout_s=5)
    mock_exec.assert_any_call("type_text", {"text": "hello"}, timeout_s=5)


@pytest.mark.anyio
async def test_direct_scroll(client):
    """'scroll down' should call scroll via bridge with default amount."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "scroll down", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "scroll", {"direction": "down", "amount": 3}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_falls_through_to_vision(client):
    """Ambiguous visual task should NOT match direct patterns — goes to VisionAgent."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch, \
         patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "find the search box and type hello", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    # No direct match → falls through to VisionAgent (async) → has a run_id
    assert data["action_triggered"] is True
    assert data.get("run_id") is not None


@pytest.mark.anyio
async def test_direct_no_bridge_falls_through(client):
    """When bridge is disconnected, direct pattern still matches but bridge
    doesn't execute — returns direct response with no run_id."""
    # Default bridge has _ws=None → connected=False
    assert not bridge.connected

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "open notepad", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    # Pattern matches so action_triggered, but bridge didn't execute
    assert data["source"] == "direct"
    assert data["action_triggered"] is True
    assert data.get("run_id") is None


@pytest.mark.anyio
async def test_greeting_fast_path(client):
    """Simple greetings should return instantly without calling the LLM."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock) as mock_chat:
        resp = await client.post("/api/chat", json={"message": "hello"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "greeting"
    assert data["action_triggered"] is False
    assert data.get("run_id") is None
    assert len(data["response"]) > 0
    # LLM should NOT have been called
    mock_chat.assert_not_called()


@pytest.mark.anyio
async def test_greeting_with_punctuation(client):
    """'hey!' should still match the greeting fast path."""
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock) as mock_chat:
        resp = await client.post("/api/chat", json={"message": "hey!"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "greeting"
    mock_chat.assert_not_called()


@pytest.mark.anyio
async def test_context_response_no_uia_dump(client):
    """Context fallback response should NOT include UIA elements."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "what am I looking at?"})

    assert resp.status_code == 200
    data = resp.json()
    # Should have window title but NOT UIA tree
    assert "Outlook" in data["response"]
    assert "Tree:" not in data["response"]
    assert "UI elements" not in data["response"]


@pytest.mark.anyio
async def test_conversational_no_uia_dump(client):
    """Non-action conversational message should NOT include UIA tree in system prompt."""
    event = _seed_event()
    await store.record(event)

    captured_messages = []

    async def mock_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return "You seem to be reading emails."

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", side_effect=mock_chat):
        # "how is my day going" is conversational, not a greeting, not an action
        resp = await client.post("/api/chat", json={"message": "how is my day going"})

    assert resp.status_code == 200
    system_msgs = [m for m in captured_messages if m.get("role") == "system"]
    assert len(system_msgs) >= 1
    system_text = system_msgs[0]["content"]
    # Should have lightweight context, not full UIA dump
    assert "User is in:" in system_text or "App:" in system_text
    assert "Current desktop state:" not in system_text


@pytest.mark.anyio
async def test_action_gets_full_context(client):
    """Action intent messages should include full desktop context in system prompt."""
    event = _seed_event()
    await store.record(event)

    captured_messages = []

    async def mock_chat(messages, **kwargs):
        captured_messages.extend(messages)
        return "Drafting email now."

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", side_effect=mock_chat):
        # "draft a reply" has action keyword "draft" but no direct bridge pattern
        resp = await client.post("/api/chat", json={"message": "draft a reply to this email"})

    assert resp.status_code == 200
    system_msgs = [m for m in captured_messages if m.get("role") == "system"]
    assert len(system_msgs) >= 1
    system_text = system_msgs[0]["content"]
    # Should contain full desktop state from to_llm_prompt()
    assert "Current desktop state:" in system_text


@pytest.mark.anyio
async def test_direct_click_by_name(client):
    """'click Save' should call click with UIA name resolution."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "click Save", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "click", {"name": "Save"}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_click_natural_phrasing(client):
    """'click on the File menu' should strip filler words."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "click on the File menu", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "click", {"name": "File menu"}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_double_click(client):
    """'double click Document.docx' should call double_click."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "double click Document.docx", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "double_click", {"name": "Document.docx"}, timeout_s=5,
    )


@pytest.mark.anyio
async def test_direct_right_click(client):
    """'right-click Desktop' should call right_click."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "right-click Desktop", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "direct"
    mock_exec.assert_called_once_with(
        "right_click", {"name": "Desktop"}, timeout_s=5,
    )


# ── SSE Streaming tests ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_stream_false_returns_json(client):
    """stream=false returns regular JSON, not SSE."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock, return_value="Hello from LLM"):
        resp = await client.post(
            "/api/chat",
            json={"message": "what am I doing?", "stream": False},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["source"] == "ollama"
    assert data["response"] == "Hello from LLM"


@pytest.mark.anyio
async def test_stream_true_returns_sse(client):
    """stream=true returns text/event-stream with SSE events."""
    event = _seed_event()
    await store.record(event)

    async def mock_stream(messages, **kwargs):
        yield {"token": "Hello", "done": False}
        yield {"token": " world", "done": False}
        yield {"token": "", "done": True}

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat_stream", side_effect=mock_stream):
        resp = await client.post(
            "/api/chat",
            json={"message": "what am I doing?", "stream": True},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    # Parse SSE events
    lines = resp.text.strip().split("\n")
    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    assert len(data_lines) >= 2  # At least one token + one done event
    # Last event should have done=True
    last = json.loads(data_lines[-1].replace("data: ", ""))
    assert last["done"] is True
    assert "conversation_id" in last


@pytest.mark.anyio
async def test_greeting_ignores_stream_flag(client):
    """Greetings always return JSON even when stream=true."""
    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat", new_callable=AsyncMock) as mock_chat:
        resp = await client.post(
            "/api/chat",
            json={"message": "hello", "stream": True},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["source"] == "greeting"
    mock_chat.assert_not_called()


@pytest.mark.anyio
async def test_direct_command_ignores_stream_flag(client):
    """Direct bridge commands always return JSON even when stream=true."""
    ws_patch, exec_patch, mock_exec = _mock_bridge_connected()
    with ws_patch, exec_patch:
        resp = await client.post(
            "/api/chat",
            json={"message": "open notepad", "allow_actions": True, "stream": True},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["source"] == "direct"


@pytest.mark.anyio
async def test_stream_final_event_has_metadata(client):
    """Final SSE event includes conversation_id, source, personality_mode."""
    event = _seed_event()
    await store.record(event)

    async def mock_stream(messages, **kwargs):
        yield {"token": "Answer", "done": False}
        yield {"token": "", "done": True}

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat_stream", side_effect=mock_stream):
        resp = await client.post(
            "/api/chat",
            json={"message": "what am I doing?", "stream": True},
        )

    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    last = json.loads(data_lines[-1].replace("data: ", ""))
    assert last["done"] is True
    assert last["source"] == "ollama"
    assert "conversation_id" in last
    assert "personality_mode" in last


@pytest.mark.anyio
async def test_stream_saves_to_chat_memory(client):
    """Streaming response saves accumulated tokens to chat memory."""
    event = _seed_event()
    await store.record(event)

    async def mock_stream(messages, **kwargs):
        yield {"token": "Hello", "done": False}
        yield {"token": " from", "done": False}
        yield {"token": " stream", "done": False}
        yield {"token": "", "done": True}

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat_stream", side_effect=mock_stream):
        resp = await client.post(
            "/api/chat",
            json={"message": "test streaming", "stream": True},
        )

    assert resp.status_code == 200
    # Extract conversation_id from final event
    lines = resp.text.strip().split("\n")
    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    last = json.loads(data_lines[-1].replace("data: ", ""))
    cid = last.get("conversation_id")
    assert cid

    # Check that the response was saved
    messages = await chat_memory.get_messages(cid, limit=10)
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) >= 1
    assert "Hello from stream" in assistant_msgs[-1]["content"]


@pytest.mark.anyio
async def test_stream_error_event(client):
    """Stream error is sent as an SSE event with error field."""
    event = _seed_event()
    await store.record(event)

    async def mock_stream(messages, **kwargs):
        yield {"token": "", "done": True, "error": "circuit breaker open"}

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=True), \
         patch.object(ollama, "chat_stream", side_effect=mock_stream):
        resp = await client.post(
            "/api/chat",
            json={"message": "test error", "stream": True},
        )

    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    # Should have error event
    events = [json.loads(ln.replace("data: ", "")) for ln in data_lines]
    error_events = [e for e in events if e.get("error")]
    assert len(error_events) >= 1


@pytest.mark.anyio
async def test_stream_fallback_to_json_when_ollama_unavailable(client):
    """When Ollama is down, stream=true falls back to JSON context response."""
    event = _seed_event()
    await store.record(event)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "what am I doing?", "stream": True},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["source"] == "context"


# ── Kill switch chat command tests ──────────────────────────────────


@pytest.mark.anyio
async def test_stop_command_matches_direct_pattern(client):
    """'stop' command matches the cancel-all direct pattern."""
    from app.routes.agent import _match_direct_pattern

    for word in ["stop", "kill", "cancel", "abort", "stop all", "kill everything", "cancel actions"]:
        result = _match_direct_pattern(word)
        assert result is not None, f"'{word}' should match cancel pattern"
        assert result[0] == "_cancel_all"


@pytest.mark.anyio
async def test_stop_command_returns_direct_source(client):
    """'stop' command returns source='direct' response."""
    event = _seed_event()
    await store.record(event)

    with patch.object(autonomy, "list_runs", new_callable=AsyncMock, return_value=[]), \
         patch.object(vision_runner, "list_runs", new_callable=AsyncMock, return_value=[]):
        resp = await client.post(
            "/api/chat",
            json={"message": "stop"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "direct"
    assert data["action_triggered"] is True


@pytest.mark.anyio
async def test_stop_command_calls_cancel(client):
    """'stop' command actually cancels running actions."""
    event = _seed_event()
    await store.record(event)

    mock_run = MagicMock()
    mock_run.run_id = "run-1"
    mock_run.status = "running"

    with patch.object(autonomy, "list_runs", new_callable=AsyncMock, return_value=[mock_run]), \
         patch.object(autonomy, "cancel", new_callable=AsyncMock) as mock_cancel, \
         patch.object(vision_runner, "list_runs", new_callable=AsyncMock, return_value=[]):
        resp = await client.post(
            "/api/chat",
            json={"message": "kill all"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "Killed 1" in data["response"]
    mock_cancel.assert_called_once_with("run-1")


@pytest.mark.anyio
async def test_stop_command_works_without_bridge(client):
    """'stop' command works even when bridge is disconnected."""
    event = _seed_event()
    await store.record(event)

    with patch.object(type(bridge), "connected", new_callable=lambda: property(lambda self: False)), \
         patch.object(autonomy, "list_runs", new_callable=AsyncMock, return_value=[]), \
         patch.object(vision_runner, "list_runs", new_callable=AsyncMock, return_value=[]):
        resp = await client.post(
            "/api/chat",
            json={"message": "stop"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "direct"
    assert "No actions" in data["response"]


# ── Recent apps context tests ────────────────────────────────────────


@pytest.mark.anyio
async def test_context_response_includes_recent_apps(client):
    """Context fallback response includes recent_apps field when foreground events exist."""
    from app.schemas import WindowEvent

    now = datetime.now(timezone.utc)

    # Seed two recent foreground events
    e1 = WindowEvent(
        type="foreground", hwnd="0x1", title="Document.docx - Word",
        process_exe="WINWORD.EXE", pid=100,
        timestamp=now,
        source="test",
    )
    e2 = WindowEvent(
        type="foreground", hwnd="0x2", title="Inbox - Outlook",
        process_exe="OUTLOOK.EXE", pid=200,
        timestamp=now,
        source="test",
    )
    await store.record(e1)
    await store.record(e2)

    with patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post("/api/chat", json={"message": "what am I working on?"})

    assert resp.status_code == 200
    data = resp.json()
    assert "recent_apps" in data
    assert isinstance(data["recent_apps"], list)
    assert len(data["recent_apps"]) >= 1


# ── Recipe → orchestrator pipeline tests ─────────────────────────────


@pytest.mark.anyio
async def test_recipe_keyword_triggers_orchestrator_with_plan(client):
    """Recipe keyword match calls autonomy.start_with_plan() with recipe steps."""
    event = _seed_event()
    await store.record(event)

    mock_run = MagicMock()
    mock_run.run_id = "recipe-run-123"
    mock_run.status = "running"
    mock_run.model_copy = MagicMock(return_value=mock_run)

    with patch.object(
        autonomy, "start_with_plan", new_callable=AsyncMock, return_value=mock_run
    ) as mock_start, \
         patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "draft reply to this email", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["run_id"] == "recipe-run-123"

    # Verify start_with_plan was called (not start)
    mock_start.assert_called_once()
    call_args = mock_start.call_args
    start_req = call_args[0][0]
    plan_steps = call_args[0][1]

    # The objective should be the recipe description
    assert "reply" in start_req.objective.lower()
    # The plan steps should come from the recipe, not the planner
    assert len(plan_steps) >= 1
    action_names = [s.action.action for s in plan_steps]
    assert "observe_desktop" in action_names
    assert "compose_text" in action_names


@pytest.mark.anyio
async def test_recipe_returns_run_id_in_response(client):
    """Recipe execution response includes the run_id from the orchestrator."""
    event = _seed_event()
    await store.record(event)

    mock_run = MagicMock()
    mock_run.run_id = "run-abc-456"
    mock_run.status = "running"
    mock_run.model_copy = MagicMock(return_value=mock_run)

    with patch.object(
        autonomy, "start_with_plan", new_callable=AsyncMock, return_value=mock_run
    ), \
         patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "summarize this document", "allow_actions": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is True
    assert data["run_id"] == "run-abc-456"


@pytest.mark.anyio
async def test_recipe_failure_handled_gracefully(client):
    """If recipe orchestrator call fails, chat doesn't crash — falls through."""
    event = _seed_event()
    await store.record(event)

    with patch.object(
        autonomy, "start_with_plan", new_callable=AsyncMock,
        side_effect=RuntimeError("orchestrator exploded"),
    ), \
         patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "draft reply", "allow_actions": True},
        )

    # Should still return 200 — not crash
    assert resp.status_code == 200
    data = resp.json()
    # action_triggered should be False since the recipe call failed
    # and no direct pattern matched either
    assert "response" in data


@pytest.mark.anyio
async def test_recipe_not_triggered_when_allow_actions_false(client):
    """Recipe keyword match is skipped when allow_actions=False."""
    event = _seed_event()
    await store.record(event)

    with patch.object(
        autonomy, "start_with_plan", new_callable=AsyncMock
    ) as mock_start, \
         patch.object(ollama, "available", new_callable=AsyncMock, return_value=False):
        resp = await client.post(
            "/api/chat",
            json={"message": "draft reply", "allow_actions": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_triggered"] is False
    mock_start.assert_not_called()


def test_recipe_to_plan_steps_conversion():
    """recipe_to_plan_steps converts Recipe step dicts to TaskStepPlan objects."""
    recipe = Recipe(
        recipe_id="test_recipe",
        name="Test Recipe",
        description="A test recipe",
        steps=[
            {"action": "observe_desktop"},
            {"action": "compose_text", "params": {"intent": "reply"}},
            {"action": "send_keys", "params": {"keys": "{ENTER}"}, "irreversible": True},
        ],
        context_patterns=[r".*"],
        keywords=["test"],
    )

    plan_steps = recipe_to_plan_steps(recipe)
    assert len(plan_steps) == 3
    assert plan_steps[0].action.action == "observe_desktop"
    assert plan_steps[0].action.parameters == {}
    assert plan_steps[1].action.action == "compose_text"
    assert plan_steps[1].action.parameters == {"intent": "reply"}
    assert plan_steps[2].action.action == "send_keys"
    assert plan_steps[2].action.parameters == {"keys": "{ENTER}"}
    assert plan_steps[2].action.irreversible is True


def test_recipe_to_plan_steps_empty():
    """recipe_to_plan_steps handles empty steps list."""
    recipe = Recipe(
        recipe_id="empty",
        name="Empty",
        description="No steps",
        steps=[],
        context_patterns=[],
        keywords=[],
    )
    assert recipe_to_plan_steps(recipe) == []
