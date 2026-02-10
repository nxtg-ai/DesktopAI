from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.vision_agent import VisionAgent, AgentAction, AgentObservation, AgentStep


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.connected = True
    bridge.execute = AsyncMock()
    return bridge


@pytest.fixture
def mock_ollama():
    ollama = MagicMock()
    ollama.chat = AsyncMock()
    ollama.chat_with_images = AsyncMock()
    return ollama


@pytest.fixture
def agent(mock_bridge, mock_ollama):
    return VisionAgent(bridge=mock_bridge, ollama=mock_ollama, max_iterations=5)


@pytest.mark.asyncio
async def test_observe_returns_observation(agent, mock_bridge):
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Outlook", "process_exe": "outlook.exe"},
        "screenshot_b64": "abc123",
        "uia": {"focused_name": "Inbox"},
    }

    obs = await agent._observe()
    assert isinstance(obs, AgentObservation)
    assert obs.window_title == "Outlook"
    assert obs.process_exe == "outlook.exe"
    assert obs.screenshot_b64 == "abc123"


@pytest.mark.asyncio
async def test_reason_with_screenshot_calls_chat_with_images(agent, mock_bridge, mock_ollama):
    import base64
    mock_ollama.chat_with_images.return_value = '{"action": "click", "parameters": {"name": "Inbox"}, "reasoning": "open inbox"}'

    obs = AgentObservation(
        screenshot_b64=base64.b64encode(b"fake-screenshot").decode(),
        uia_summary='{"focused_name": "Inbox"}',
        window_title="Outlook",
        process_exe="outlook.exe",
        timestamp=MagicMock(),
    )

    action = await agent._reason("check inbox", obs, [])
    assert action.action == "click"
    assert action.parameters["name"] == "Inbox"
    mock_ollama.chat_with_images.assert_called_once()


@pytest.mark.asyncio
async def test_reason_without_screenshot_calls_chat(agent, mock_bridge, mock_ollama):
    mock_ollama.chat.return_value = '{"action": "open_application", "parameters": {"application": "outlook.exe"}, "reasoning": "need to open outlook"}'

    obs = AgentObservation(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Desktop",
        process_exe="explorer.exe",
        timestamp=MagicMock(),
    )

    action = await agent._reason("check inbox", obs, [])
    assert action.action == "open_application"
    mock_ollama.chat.assert_called_once()


def test_parse_valid_json_action():
    response = '{"action": "click", "parameters": {"name": "Send"}, "reasoning": "sending email"}'
    action = VisionAgent._parse_action(response)
    assert action.action == "click"
    assert action.parameters["name"] == "Send"
    assert action.reasoning == "sending email"


def test_parse_invalid_json_falls_back_to_wait():
    response = "I think we should click the send button"
    action = VisionAgent._parse_action(response)
    assert action.action == "wait"
    assert "parse error" in action.reasoning


def test_parse_empty_response_falls_back_to_wait():
    action = VisionAgent._parse_action(None)
    assert action.action == "wait"
    assert action.reasoning == "empty response"


def test_parse_json_in_code_block():
    response = '```json\n{"action": "done", "parameters": {}, "reasoning": "task complete"}\n```'
    action = VisionAgent._parse_action(response)
    assert action.action == "done"
    assert action.reasoning == "task complete"


@pytest.mark.asyncio
async def test_run_loop_exits_on_done(agent, mock_bridge, mock_ollama):
    # Observe returns some state
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Outlook", "process_exe": "outlook.exe"},
    }
    # Reason returns "done" immediately
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "already done"}'

    steps = await agent.run("check inbox")
    assert len(steps) == 1
    assert steps[0].action.action == "done"


@pytest.mark.asyncio
async def test_run_loop_exits_at_max_iterations(agent, mock_bridge, mock_ollama):
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Desktop", "process_exe": "explorer.exe"},
    }
    # Keep returning "wait" so we hit max iterations
    mock_ollama.chat.return_value = '{"action": "wait", "parameters": {}, "reasoning": "waiting"}'

    steps = await agent.run("check inbox")
    assert len(steps) == 5  # max_iterations


@pytest.mark.asyncio
async def test_on_step_callback_invoked(agent, mock_bridge, mock_ollama):
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Outlook", "process_exe": "outlook.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "done"}'

    callback_steps = []
    def on_step(step):
        callback_steps.append(step)

    await agent.run("check inbox", on_step=on_step)
    assert len(callback_steps) == 1
    assert callback_steps[0].action.action == "done"


@pytest.mark.asyncio
async def test_act_sends_correct_command(agent, mock_bridge):
    mock_bridge.execute.return_value = {"ok": True, "result": {"clicked": "Send"}}

    action = AgentAction(action="click", parameters={"name": "Send"}, reasoning="send email")
    result = await agent._act(action)

    assert result["ok"] is True
    mock_bridge.execute.assert_called_with("click", {"name": "Send"}, timeout_s=10)


@pytest.mark.asyncio
async def test_act_error_recorded_in_step(agent, mock_bridge, mock_ollama):
    call_count = 0

    async def bridge_execute(action, params=None, timeout_s=None):
        nonlocal call_count
        call_count += 1
        if action == "observe":
            return {
                "ok": True,
                "result": {"window_title": "Test", "process_exe": "test.exe"},
            }
        raise RuntimeError("connection lost")

    mock_bridge.execute = bridge_execute
    mock_ollama.chat.return_value = '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try"}'

    # Override to return done after first error
    responses = iter([
        '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try"}',
        '{"action": "done", "parameters": {}, "reasoning": "giving up"}',
    ])
    mock_ollama.chat.side_effect = lambda msgs: next(responses)

    steps = await agent.run("test")
    # First step should have an error
    error_steps = [s for s in steps if s.error is not None]
    assert len(error_steps) >= 1
    assert "connection lost" in error_steps[0].error
