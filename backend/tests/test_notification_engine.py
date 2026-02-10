"""Tests for the NotificationEngine and its rules."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import time
from unittest.mock import AsyncMock

import pytest
from app.notification_engine import (
    AppSwitchRule,
    IdleRule,
    NotificationEngine,
    SessionMilestoneRule,
    StateSnapshot,
)
from app.notifications import NotificationStore
from app.ws import WebSocketHub


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_idle_rule_triggers():
    rule = IdleRule(threshold_s=60)
    snapshot = StateSnapshot(
        idle=True, idle_since_ts=time.time() - 120, event_count=5
    )
    result = rule.check(snapshot)
    assert result is not None
    assert result["rule"] == "idle"
    assert "idle" in result["title"].lower()


def test_idle_rule_below_threshold():
    rule = IdleRule(threshold_s=300)
    snapshot = StateSnapshot(
        idle=True, idle_since_ts=time.time() - 10, event_count=5
    )
    result = rule.check(snapshot)
    assert result is None


def test_app_switch_rule_triggers():
    rule = AppSwitchRule(max_switches=3, window_s=60)
    triggered = None
    for i in range(5):
        snapshot = StateSnapshot(process_exe=f"app{i}.exe", event_count=i + 1)
        result = rule.check(snapshot)
        if result is not None:
            triggered = result
    assert triggered is not None
    assert triggered["rule"] == "app_switch"


def test_app_switch_rule_normal_usage():
    rule = AppSwitchRule(max_switches=10, window_s=60)
    # Only 2 switches
    for name in ["app1.exe", "app2.exe"]:
        snapshot = StateSnapshot(process_exe=name, event_count=1)
        result = rule.check(snapshot)
    assert result is None


def test_session_milestone_triggers():
    rule = SessionMilestoneRule()
    # First call sets start time
    rule.check(StateSnapshot(event_count=1))
    # Simulate 1 hour passed
    rule._start_time = time.time() - 3700
    result = rule.check(StateSnapshot(event_count=10))
    assert result is not None
    assert result["rule"] == "session_milestone"
    assert "1 hour" in result["message"]


@pytest.mark.anyio
async def test_disabled_notifications():
    store = NotificationStore(path=":memory:")
    hub = WebSocketHub()
    hub.broadcast_json = AsyncMock()
    engine = NotificationEngine(store, hub, enabled=False, idle_threshold_s=1)

    snapshot = StateSnapshot(idle=True, idle_since_ts=time.time() - 600, event_count=5)
    await engine.evaluate(snapshot)

    hub.broadcast_json.assert_not_called()
    assert await store.unread_count() == 0
