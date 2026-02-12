"""Tests for VisionAutonomousRunner — singleton persistence and run lifecycle."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.autonomy import VisionAutonomousRunner
from app.schemas import AutonomyStartRequest
from app.vision_agent import AgentAction, AgentObservation, AgentStep


def _make_observation(**kw):
    from datetime import datetime, timezone
    defaults = dict(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Test",
        process_exe="test.exe",
        timestamp=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return AgentObservation(**defaults)


def _make_done_step():
    return AgentStep(
        observation=_make_observation(),
        action=AgentAction(action="done", parameters={}, reasoning="done"),
        result={"status": "completed"},
    )


def _make_failed_step():
    return AgentStep(
        observation=_make_observation(),
        action=AgentAction(action="click", parameters={"name": "X"}, reasoning="try"),
        error="element not found",
    )


def _mock_agent(steps=None):
    """Create a mock VisionAgent that returns given steps."""
    agent = MagicMock()
    if steps is None:
        steps = [_make_done_step()]
    agent.run = AsyncMock(return_value=steps)
    return agent


@pytest.mark.asyncio
async def test_start_creates_run_and_returns_id():
    runner = VisionAutonomousRunner(vision_agent=_mock_agent())
    run = await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    assert run.run_id
    assert run.status == "running"
    assert run.objective == "test"


@pytest.mark.asyncio
async def test_run_persists_in_runner():
    """The run should be queryable from the runner after start."""
    runner = VisionAutonomousRunner(vision_agent=_mock_agent())
    run = await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    # Wait for the background task to complete
    await asyncio.sleep(0.1)
    fetched = await runner.get_run(run.run_id)
    assert fetched is not None
    assert fetched.run_id == run.run_id


@pytest.mark.asyncio
async def test_completed_run_has_correct_status():
    """A run with a done step should reach 'completed' status."""
    runner = VisionAutonomousRunner(vision_agent=_mock_agent([_make_done_step()]))
    run = await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    deadline = time.time() + 2.0
    while time.time() < deadline:
        fetched = await runner.get_run(run.run_id)
        if fetched and fetched.status == "completed":
            break
        await asyncio.sleep(0.05)
    fetched = await runner.get_run(run.run_id)
    assert fetched is not None
    assert fetched.status == "completed"


@pytest.mark.asyncio
async def test_failed_run_on_max_iterations():
    """A run that never sends 'done' should end as 'failed'."""
    steps = [_make_failed_step()] * 3
    runner = VisionAutonomousRunner(vision_agent=_mock_agent(steps))
    run = await runner.start(AutonomyStartRequest(objective="test", max_iterations=3))
    deadline = time.time() + 2.0
    while time.time() < deadline:
        fetched = await runner.get_run(run.run_id)
        if fetched and fetched.status in {"failed", "completed"}:
            break
        await asyncio.sleep(0.05)
    fetched = await runner.get_run(run.run_id)
    assert fetched is not None
    assert fetched.status == "failed"


@pytest.mark.asyncio
async def test_list_runs_returns_all():
    runner = VisionAutonomousRunner(vision_agent=_mock_agent())
    run1 = await runner.start(AutonomyStartRequest(objective="a", max_iterations=5))
    await asyncio.sleep(0.05)
    run2 = await runner.start(AutonomyStartRequest(objective="b", max_iterations=5))
    await asyncio.sleep(0.05)
    runs = await runner.list_runs(limit=10)
    ids = {r.run_id for r in runs}
    assert run1.run_id in ids
    assert run2.run_id in ids


@pytest.mark.asyncio
async def test_cancel_sets_cancelled_status():
    """Cancelling a running run should set status to 'cancelled'."""
    # Use a slow agent that won't finish immediately
    agent = MagicMock()

    async def slow_run(_objective, on_step=None):  # noqa: ARG001
        await asyncio.sleep(10)
        return [_make_done_step()]

    agent.run = slow_run
    runner = VisionAutonomousRunner(vision_agent=agent)
    run = await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    await asyncio.sleep(0.05)
    cancelled = await runner.cancel(run.run_id)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_get_run_returns_none_for_unknown_id():
    runner = VisionAutonomousRunner()
    result = await runner.get_run("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_agent_replaces_agent():
    """set_agent should allow replacing the vision agent before next run."""
    agent1 = _mock_agent()
    agent2 = _mock_agent()
    runner = VisionAutonomousRunner(vision_agent=agent1)
    runner.set_agent(agent2)
    await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    await asyncio.sleep(0.2)
    agent2.run.assert_awaited_once()
    agent1.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_run_update_callback_fires():
    """The on_run_update callback should be called at least once."""
    callback = AsyncMock()
    runner = VisionAutonomousRunner(
        vision_agent=_mock_agent(), on_run_update=callback
    )
    await runner.start(AutonomyStartRequest(objective="test", max_iterations=5))
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if callback.call_count >= 2:  # start + completion
            break
        await asyncio.sleep(0.05)
    assert callback.call_count >= 2
