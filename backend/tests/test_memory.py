from __future__ import annotations

import json

import pytest

from app.memory import Trajectory, TrajectoryStore, format_trajectory_context
from app.vision_agent import AgentAction, AgentObservation, AgentStep
from datetime import datetime, timezone


def _make_store() -> TrajectoryStore:
    return TrajectoryStore(path=":memory:", max_trajectories=100)


def _make_step(action: str = "click", reasoning: str = "test", error=None) -> AgentStep:
    obs = AgentObservation(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Test",
        process_exe="test.exe",
        timestamp=datetime.now(timezone.utc),
    )
    act = AgentAction(action=action, parameters={"name": "X"}, reasoning=reasoning, confidence=0.9)
    step = AgentStep(observation=obs, action=act)
    step.result = {"ok": True}
    step.error = error
    return step


@pytest.mark.asyncio
async def test_save_and_get_trajectory():
    store = _make_store()
    steps = [_make_step(), _make_step(action="done", reasoning="finished")]
    traj = await store.save_trajectory("t1", "open notepad", steps, "completed")

    assert traj.trajectory_id == "t1"
    assert traj.objective == "open notepad"
    assert traj.outcome == "completed"
    assert traj.step_count == 2

    retrieved = await store.get_trajectory("t1")
    assert retrieved is not None
    assert retrieved.trajectory_id == "t1"
    assert retrieved.outcome == "completed"


@pytest.mark.asyncio
async def test_get_nonexistent_trajectory():
    store = _make_store()
    result = await store.get_trajectory("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_list_trajectories():
    store = _make_store()
    for i in range(5):
        await store.save_trajectory(f"t{i}", f"task {i}", [_make_step()], "completed")

    results = await store.list_trajectories(limit=3)
    assert len(results) == 3
    # Most recent first
    assert results[0].trajectory_id == "t4"


@pytest.mark.asyncio
async def test_list_trajectories_empty():
    store = _make_store()
    results = await store.list_trajectories()
    assert results == []


@pytest.mark.asyncio
async def test_find_similar():
    store = _make_store()
    await store.save_trajectory("t1", "open notepad and type hello", [_make_step()], "completed")
    await store.save_trajectory("t2", "open outlook and check email", [_make_step()], "completed")
    await store.save_trajectory("t3", "open notepad and save file", [_make_step()], "completed")

    results = await store.find_similar("open notepad", limit=5)
    assert len(results) >= 1
    objectives = [r.objective for r in results]
    # Both notepad trajectories should match
    assert any("notepad" in obj for obj in objectives)


@pytest.mark.asyncio
async def test_find_similar_no_match():
    store = _make_store()
    await store.save_trajectory("t1", "open notepad", [_make_step()], "completed")
    results = await store.find_similar("zzzznonexistent", limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_retention_enforced():
    store = TrajectoryStore(path=":memory:", max_trajectories=3)
    for i in range(5):
        await store.save_trajectory(f"t{i}", f"task {i}", [_make_step()], "completed")

    results = await store.list_trajectories(limit=10)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_upsert_overwrites():
    store = _make_store()
    await store.save_trajectory("t1", "open notepad", [_make_step()], "failed")
    await store.save_trajectory("t1", "open notepad", [_make_step(), _make_step()], "completed")

    traj = await store.get_trajectory("t1")
    assert traj is not None
    assert traj.outcome == "completed"
    assert traj.step_count == 2


@pytest.mark.asyncio
async def test_step_error_stored():
    store = _make_store()
    step = _make_step(error="connection lost")
    await store.save_trajectory("t1", "task", [step], "failed")

    traj = await store.get_trajectory("t1")
    assert traj is not None
    steps_data = json.loads(traj.steps_json)
    assert steps_data[0]["error"] == "connection lost"


# ── format_trajectory_context tests ──────────────────────────────────


def _make_trajectory(
    objective: str = "open notepad",
    outcome: str = "completed",
    steps_json: str | None = None,
    step_count: int = 2,
) -> Trajectory:
    if steps_json is None:
        steps_json = json.dumps([
            {"action": "click", "reasoning": "click button", "confidence": 0.9, "error": None},
            {"action": "done", "reasoning": "finished", "confidence": 1.0, "error": None},
        ])
    return Trajectory(
        trajectory_id="t1",
        objective=objective,
        steps_json=steps_json,
        outcome=outcome,
        step_count=step_count,
        created_at="2025-07-01T12:00:00+00:00",
    )


def test_format_empty_list():
    assert format_trajectory_context([]) == ""


def test_format_single_trajectory():
    traj = _make_trajectory()
    result = format_trajectory_context([traj])
    assert '[COMPLETED] "open notepad"' in result
    assert "click" in result
    assert "done" in result


def test_format_failed_trajectory():
    traj = _make_trajectory(outcome="failed")
    result = format_trajectory_context([traj])
    assert "[FAILED]" in result


def test_format_truncation():
    traj = _make_trajectory()
    result = format_trajectory_context([traj], max_chars=30)
    assert len(result) <= 30
    assert result.endswith("...")


def test_format_invalid_json_steps():
    traj = _make_trajectory(steps_json="not-json")
    result = format_trajectory_context([traj])
    # Should still produce the header line without crashing
    assert '[COMPLETED] "open notepad"' in result


def test_format_step_with_error():
    steps = json.dumps([
        {"action": "click", "reasoning": "try clicking", "error": "element not found"},
    ])
    traj = _make_trajectory(steps_json=steps, step_count=1)
    result = format_trajectory_context([traj])
    assert "ERR:" in result
    assert "element not found" in result


def test_format_caps_steps_at_8():
    steps = json.dumps([
        {"action": f"step_{i}", "reasoning": f"reason {i}"}
        for i in range(12)
    ])
    traj = _make_trajectory(steps_json=steps, step_count=12)
    result = format_trajectory_context([traj])
    assert "step_7" in result
    assert "step_8" not in result
