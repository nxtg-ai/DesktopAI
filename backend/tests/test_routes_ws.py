"""Tests for the /ws WebSocket route handler in ws_route.py."""

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from app.deps import autonomy, hub, store
from app.main import app
from app.schemas import AutonomyRunRecord, WindowEvent
from starlette.testclient import TestClient


def _make_event(**overrides) -> WindowEvent:
    """Create a minimal WindowEvent for testing."""
    defaults = {
        "hwnd": "0x1234",
        "title": "Test Window",
        "process_exe": "test.exe",
        "pid": 1000,
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return WindowEvent(**defaults)


def _make_run(**overrides) -> AutonomyRunRecord:
    """Create a minimal AutonomyRunRecord for testing."""
    now = datetime.now(timezone.utc)
    defaults = {
        "run_id": "test-run-001",
        "task_id": "test-task-001",
        "objective": "test objective",
        "planner_mode": "deterministic",
        "status": "running",
        "iteration": 2,
        "max_iterations": 10,
        "parallel_agents": 1,
        "auto_approve_irreversible": False,
        "autonomy_level": "supervised",
        "started_at": now,
        "updated_at": now,
        "agent_log": [],
    }
    defaults.update(overrides)
    return AutonomyRunRecord(**defaults)


def _run_async(coro):
    """Run an async coroutine from sync test code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _reset_state():
    _run_async(store.hydrate([], None, False, None))
    hub._clients.clear()


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset():
    """Reset store and hub between tests."""
    _reset_state()
    yield
    _reset_state()


# ── Tests ─────────────────────────────────────────────────────────────


def test_ws_connect_receives_snapshot():
    """Connect to /ws and verify snapshot structure."""
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "snapshot"
        assert "state" in data
        assert "events" in data
        assert "autonomy_run" in data
        assert "bridge_connected" in data
        state = data["state"]
        assert "current" in state
        assert "event_count" in state
        assert "idle" in state
        assert "idle_since" in state
        assert "category" in state


def test_ws_snapshot_empty_state():
    """Empty store yields null current, zero events, idle=False."""
    mock_bridge = MagicMock()
    mock_bridge.connected = False  # Ensure clean bridge state across test ordering
    with patch("app.routes.ws_route.bridge", mock_bridge):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == "snapshot"
            assert data["state"]["current"] is None
            assert data["state"]["event_count"] == 0
            assert data["state"]["idle"] is False
            assert data["state"]["idle_since"] is None
            assert data["state"]["category"] is None
            assert data["autonomy_run"] is None
            assert data["bridge_connected"] is False
            assert data["events"] == []


def test_ws_snapshot_with_events():
    """Hydrated store includes events in snapshot."""
    events = [_make_event(title=f"Window {i}") for i in range(5)]
    current = events[-1]
    _run_async(store.hydrate(events, current, False, None))

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["state"]["event_count"] == 5
        assert len(data["events"]) == 5
        assert data["state"]["current"] is not None
        assert data["state"]["current"]["title"] == "Window 4"


def test_ws_snapshot_with_autonomy_run():
    """Active autonomy run appears in snapshot."""
    mock_run = _make_run(run_id="run-abc", status="running", iteration=3)
    with patch.object(autonomy, "list_runs", new_callable=AsyncMock, return_value=[mock_run]):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["autonomy_run"] is not None
            assert data["autonomy_run"]["run_id"] == "run-abc"
            assert data["autonomy_run"]["status"] == "running"
            assert data["autonomy_run"]["iteration"] == 3


def test_ws_hub_capacity_rejects():
    """Connection is rejected when hub is at capacity."""
    original_max = hub._max_connections
    hub._max_connections = 0
    try:
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
    finally:
        hub._max_connections = original_max


def test_ws_disconnect_cleans_up():
    """Hub connection count decreases after client disconnects."""
    client = TestClient(app)
    count_before = hub.connection_count
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert hub.connection_count == count_before + 1
    # After context manager exits, the connection is closed
    assert hub.connection_count == count_before


def test_ws_bridge_connected_true():
    """bridge_connected reflects bridge.connected state."""
    mock_bridge = MagicMock()
    mock_bridge.connected = True  # MagicMock().connected is truthy by default — set explicitly
    with patch("app.routes.ws_route.bridge", mock_bridge):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["bridge_connected"] is True


def test_ws_bridge_disconnected_false():
    """bridge_connected is False when bridge is disconnected."""
    mock_bridge = MagicMock()
    mock_bridge.connected = False  # MUST set explicitly — MagicMock attr would be truthy
    with patch("app.routes.ws_route.bridge", mock_bridge):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["bridge_connected"] is False
