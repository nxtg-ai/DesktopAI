from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.action_executor import BridgeActionExecutor
from app.schemas import TaskAction


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.connected = True
    bridge.execute = AsyncMock()
    return bridge


@pytest.fixture
def executor(mock_bridge):
    return BridgeActionExecutor(bridge=mock_bridge, timeout_s=5)


@pytest.mark.asyncio
async def test_observe_desktop_via_bridge(executor, mock_bridge):
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Outlook", "process_exe": "outlook.exe"},
        "screenshot_b64": "base64data",
    }
    action = TaskAction(action="observe_desktop")
    result = await executor.execute(action, objective="check desktop")

    assert result.ok
    assert result.result["action"] == "observe_desktop"
    assert result.result["screenshot_available"] is True
    mock_bridge.execute.assert_called_once_with("observe", timeout_s=5)


@pytest.mark.asyncio
async def test_click_via_bridge(executor, mock_bridge):
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"clicked": "Send"},
    }
    action = TaskAction(action="click", parameters={"name": "Send", "automation_id": "btn_send"})
    result = await executor.execute(action, objective="send email")

    assert result.ok
    mock_bridge.execute.assert_called_once_with(
        "click", {"name": "Send", "automation_id": "btn_send"}, timeout_s=5,
    )


@pytest.mark.asyncio
async def test_compose_text_with_llm(executor, mock_bridge):
    mock_ollama = AsyncMock()
    mock_ollama.chat = AsyncMock(return_value="Hello, thanks for your email.")
    executor._ollama = mock_ollama

    mock_ctx = MagicMock()
    mock_ctx.to_llm_prompt.return_value = "Window: Outlook"
    mock_ctx.get_screenshot_bytes.return_value = None

    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"typed": "Hello, thanks for your email."},
    }

    action = TaskAction(action="compose_text")
    result = await executor.execute(action, objective="reply to email", desktop_context=mock_ctx)

    assert result.ok
    mock_ollama.chat.assert_called_once()
    mock_bridge.execute.assert_called_once()


@pytest.mark.asyncio
async def test_not_connected_returns_error(mock_bridge):
    mock_bridge.connected = False
    executor = BridgeActionExecutor(bridge=mock_bridge, timeout_s=5)

    action = TaskAction(action="observe_desktop")
    result = await executor.execute(action, objective="check desktop")

    assert not result.ok
    assert result.error is not None and "not connected" in result.error


@pytest.mark.asyncio
async def test_status_reflects_connection(mock_bridge):
    executor = BridgeActionExecutor(bridge=mock_bridge, timeout_s=5)
    status = executor.status()
    assert status["available"] is True
    assert status["bridge_connected"] is True
    assert status["mode"] == "bridge"

    mock_bridge.connected = False
    status = executor.status()
    assert status["available"] is False
