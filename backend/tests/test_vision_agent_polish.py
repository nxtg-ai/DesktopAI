from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.vision_agent import VisionAgent


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


# --- Confidence gating ---

@pytest.mark.asyncio
async def test_low_confidence_action_gated_to_wait(mock_bridge, mock_ollama):
    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama,
        max_iterations=3, min_confidence=0.5,
    )
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    # Return low-confidence action, then done
    responses = iter([
        '{"action": "click", "parameters": {"name": "X"}, "reasoning": "maybe", "confidence": 0.2}',
        '{"action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9}',
    ])
    mock_ollama.chat.side_effect = lambda msgs: next(responses)

    steps = await agent.run("test")
    # First step should be gated to wait
    assert steps[0].action.action == "wait"
    assert "low confidence" in steps[0].action.reasoning
    assert steps[0].result["gated_action"] == "click"
    # Second step should complete
    assert steps[1].action.action == "done"


@pytest.mark.asyncio
async def test_high_confidence_action_passes(mock_bridge, mock_ollama):
    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama,
        max_iterations=3, min_confidence=0.5,
    )
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "done", "confidence": 0.9}'

    steps = await agent.run("test")
    assert len(steps) == 1
    assert steps[0].action.action == "done"


@pytest.mark.asyncio
async def test_default_confidence_is_1(mock_bridge, mock_ollama):
    """Actions without explicit confidence should default to 1.0 (always pass)."""
    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama,
        max_iterations=2, min_confidence=0.5,
    )
    mock_bridge.execute.return_value = {
        "ok": True,
        "result": {"window_title": "Test", "process_exe": "test.exe"},
    }
    mock_ollama.chat.return_value = '{"action": "done", "parameters": {}, "reasoning": "ok"}'

    steps = await agent.run("test")
    assert steps[0].action.confidence == 1.0
    assert steps[0].action.action == "done"


def test_parse_action_with_confidence():
    action = VisionAgent._parse_action(
        '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try", "confidence": 0.75}'
    )
    assert action.confidence == 0.75


def test_parse_action_default_confidence():
    action = VisionAgent._parse_action(
        '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try"}'
    )
    assert action.confidence == 1.0


# --- Error recovery ---

@pytest.mark.asyncio
async def test_consecutive_errors_abort(mock_bridge, mock_ollama):
    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama,
        max_iterations=10, max_consecutive_errors=2, error_backoff_ms=0,
    )
    call_count = 0

    async def bridge_execute(action, params=None, timeout_s=None):
        nonlocal call_count
        call_count += 1
        if action == "observe":
            return {"ok": True, "result": {"window_title": "T", "process_exe": "t"}}
        raise RuntimeError("bridge down")

    mock_bridge.execute = bridge_execute
    mock_ollama.chat.return_value = '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try"}'

    steps = await agent.run("test")
    error_steps = [s for s in steps if s.error is not None]
    assert len(error_steps) == 2  # Should stop after 2 consecutive errors


@pytest.mark.asyncio
async def test_errors_reset_on_success(mock_bridge, mock_ollama):
    agent = VisionAgent(
        bridge=mock_bridge, ollama=mock_ollama,
        max_iterations=10, max_consecutive_errors=3, error_backoff_ms=0,
    )
    call_count = 0

    async def bridge_execute(action, params=None, timeout_s=None):
        nonlocal call_count
        call_count += 1
        if action == "observe":
            return {"ok": True, "result": {"window_title": "T", "process_exe": "t"}}
        # First call fails, second succeeds (alternating)
        if call_count % 3 == 0:
            raise RuntimeError("intermittent")
        return {"ok": True}

    mock_bridge.execute = bridge_execute
    responses = iter([
        '{"action": "click", "parameters": {"name": "X"}, "reasoning": "try"}',
        '{"action": "click", "parameters": {"name": "Y"}, "reasoning": "try2"}',
        '{"action": "click", "parameters": {"name": "Z"}, "reasoning": "try3"}',
        '{"action": "done", "parameters": {}, "reasoning": "ok"}',
    ])
    mock_ollama.chat.side_effect = lambda msgs: next(responses)

    steps = await agent.run("test")
    # Should not abort — errors are interspersed with successes
    assert steps[-1].action.action == "done"


@pytest.mark.asyncio
async def test_min_confidence_clamped():
    bridge = MagicMock()
    ollama = MagicMock()
    agent = VisionAgent(bridge=bridge, ollama=ollama, min_confidence=1.5)
    assert agent._min_confidence == 1.0

    agent2 = VisionAgent(bridge=bridge, ollama=ollama, min_confidence=-0.5)
    assert agent2._min_confidence == 0.0
