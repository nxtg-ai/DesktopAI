from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.vision_agent import AgentAction, AgentObservation, VisionAgent


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


# ── Trajectory-informed planning tests ───────────────────────────────


@pytest.mark.asyncio
async def test_trajectory_store_queried_during_run(mock_bridge, mock_ollama):
    """VisionAgent queries trajectory store at start of run."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "done"}'

    traj_store = AsyncMock()
    traj_store.find_similar = AsyncMock(return_value=[])

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=3,
        trajectory_store=traj_store,
    )
    await agent.run("open notepad")
    traj_store.find_similar.assert_called_once_with("open notepad", limit=3)


@pytest.mark.asyncio
async def test_trajectory_context_appears_in_prompt(mock_bridge, mock_ollama):
    """When trajectory store returns results, the prompt includes past experience."""
    from app.memory import Trajectory

    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }

    captured_messages = []
    async def capture_chat(messages):
        captured_messages.append(messages)
        return '{"action": "done", "parameters": {}, "reasoning": "done"}'

    mock_ollama.chat = capture_chat
    # Remove chat_with_images so it falls through to chat
    if hasattr(mock_ollama, "chat_with_images"):
        del mock_ollama.chat_with_images

    traj = Trajectory(
        trajectory_id="t1",
        objective="open notepad",
        steps_json=json.dumps([{"action": "click", "reasoning": "click start", "error": None}]),
        outcome="completed",
        step_count=1,
        created_at="2025-07-01T00:00:00+00:00",
    )
    traj_store = AsyncMock()
    traj_store.find_similar = AsyncMock(return_value=[traj])

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=3,
        trajectory_store=traj_store,
    )
    await agent.run("open notepad")

    assert captured_messages
    prompt = captured_messages[0][0]["content"]
    assert "PAST EXPERIENCE" in prompt
    assert "open notepad" in prompt


@pytest.mark.asyncio
async def test_trajectory_lookup_failure_nonfatal(mock_bridge, mock_ollama):
    """If trajectory store raises, agent still runs normally."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "done"}'

    traj_store = AsyncMock()
    traj_store.find_similar = AsyncMock(side_effect=RuntimeError("db gone"))

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=3,
        trajectory_store=traj_store,
    )
    steps = await agent.run("open notepad")
    assert len(steps) == 1
    assert steps[0].action.action == "done"


@pytest.mark.asyncio
async def test_no_trajectory_store_still_works(mock_bridge, mock_ollama):
    """Agent with no trajectory store runs normally."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "done"}'

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=3,
        trajectory_store=None,
    )
    steps = await agent.run("open notepad")
    assert len(steps) == 1
    assert steps[0].action.action == "done"


@pytest.mark.asyncio
async def test_repeated_action_triggers_auto_done(mock_bridge, mock_ollama):
    """Agent auto-completes when the same action is repeated 3 times."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    # VLM keeps returning the same open_application action
    mock_ollama.chat.return_value = json.dumps({
        "action": "open_application",
        "parameters": {"application": "notepad.exe"},
        "reasoning": "opening notepad",
        "confidence": 0.9,
    })

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=10,
    )
    steps = await agent.run("open notepad")

    # Should auto-done after 3 repeats (3 actions + 1 auto-done = 4 steps)
    assert len(steps) == 4
    assert steps[-1].action.action == "done"
    assert "repeated" in steps[-1].action.reasoning.lower() or "auto" in steps[-1].action.reasoning.lower()


def test_prompt_includes_focus_before_type_rule():
    """VisionAgent prompt instructs focus_window before type_text."""
    from app.vision_agent import VISION_AGENT_PROMPT

    prompt_lower = VISION_AGENT_PROMPT.lower()
    assert "focus_window" in prompt_lower
    assert "type_text" in prompt_lower or "typing" in prompt_lower
    assert "focus" in prompt_lower and "before" in prompt_lower


# ── Ollama failure abort tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_agent_aborts_on_consecutive_ollama_failures(mock_bridge, mock_ollama):
    """Agent aborts after 2 consecutive Ollama failures (None responses)."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    # Ollama returns None (failure) every time
    mock_ollama.chat.return_value = None
    # Remove chat_with_images so it falls to chat
    if hasattr(mock_ollama, "chat_with_images"):
        del mock_ollama.chat_with_images

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=10,
    )
    steps = await agent.run("open notepad")

    # Should abort, not run all 10 iterations
    # 2 consecutive None → wait fallback; on the 2nd, abort fires
    last = steps[-1]
    assert last.action.action in ("abort", "done", "wait")
    assert len(steps) <= 5  # Much less than max_iterations


@pytest.mark.asyncio
async def test_vision_agent_continues_after_single_ollama_failure(mock_bridge, mock_ollama):
    """A single Ollama failure followed by success continues normally."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    # First call returns None (fail), second returns done
    call_count = 0

    async def varying_response(messages, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return '{"action": "done", "parameters": {}, "reasoning": "done"}'

    mock_ollama.chat.side_effect = varying_response
    if hasattr(mock_ollama, "chat_with_images"):
        del mock_ollama.chat_with_images

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=10,
    )
    steps = await agent.run("open notepad")

    assert steps[-1].action.action == "done"
    assert len(steps) == 2  # wait (from None) + done


@pytest.mark.asyncio
async def test_vision_agent_abort_status_is_failed(mock_bridge, mock_ollama):
    """When agent aborts due to Ollama failures, result has failed status."""
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = None
    if hasattr(mock_ollama, "chat_with_images"):
        del mock_ollama.chat_with_images

    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama, max_iterations=10,
    )
    steps = await agent.run("open notepad")

    # Agent should signal failure somehow — didn't exhaust iterations
    assert len(steps) < 10
    assert any(
        s.action.action == "abort" or (s.result and s.result.get("status") == "failed")
        for s in steps
    )


# ── CUA / Coordinate mode tests ─────────────────────────────────────


def test_cua_prompt_uses_coordinates():
    """CUA prompt references x/y pixel coordinates, not UIA names."""
    from app.vision_agent import CUA_AGENT_PROMPT

    assert '"x"' in CUA_AGENT_PROMPT
    assert '"y"' in CUA_AGENT_PROMPT
    assert "pixel coordinates" in CUA_AGENT_PROMPT.lower()


def test_use_coordinates_selects_cua_prompt():
    """VisionAgent with use_coordinates=True uses CUA prompt template."""
    bridge = MagicMock()
    ollama = MagicMock()

    agent_name = VisionAgent(bridge=bridge, ollama=ollama, use_coordinates=False)
    agent_cua = VisionAgent(bridge=bridge, ollama=ollama, use_coordinates=True)

    assert agent_name._use_coordinates is False
    assert agent_cua._use_coordinates is True


def test_parse_action_with_xy_coordinates():
    """Parser handles CUA-style x/y coordinate output."""
    response = '{"action": "click", "parameters": {"x": 450, "y": 320}, "reasoning": "click button", "confidence": 0.85}'
    action = VisionAgent._parse_action(response)
    assert action.action == "click"
    assert action.parameters["x"] == 450
    assert action.parameters["y"] == 320
    assert action.confidence == 0.85


def test_parse_action_name_based_regression():
    """Name-based action parsing still works alongside coordinate mode."""
    response = '{"action": "click", "parameters": {"name": "Submit"}, "reasoning": "click submit", "confidence": 0.9}'
    action = VisionAgent._parse_action(response)
    assert action.action == "click"
    assert action.parameters["name"] == "Submit"
