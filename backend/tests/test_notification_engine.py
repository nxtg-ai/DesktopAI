"""Tests for the NotificationEngine and its rules."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import time
from unittest.mock import AsyncMock

import pytest
from app.notification_engine import (
    AppSwitchRule,
    ContextInsightRule,
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


# --- ContextInsightRule tests ---


def test_context_insight_short_name_windows():
    rule = ContextInsightRule()
    assert rule._short_name("C:\\Windows\\System32\\notepad.exe") == "notepad"


def test_context_insight_short_name_unix():
    rule = ContextInsightRule()
    assert rule._short_name("/usr/bin/firefox") == "firefox"


def test_context_insight_short_name_bare():
    rule = ContextInsightRule()
    assert rule._short_name("chrome.exe") == "chrome"


def test_context_insight_toggle_triggers():
    """Toggling between two apps enough times triggers an insight."""
    rule = ContextInsightRule(toggle_window_s=300, toggle_min_switches=4)
    result = None
    # Simulate A→B→A→B→A→B (6 transitions between pair)
    apps = ["outlook.exe", "excel.exe"] * 4
    for app in apps:
        snap = StateSnapshot(process_exe=app, event_count=1)
        r = rule.check(snap)
        if r is not None:
            result = r
    assert result is not None
    assert result["rule"] == "context_insight_toggle"
    assert "outlook" in result["message"].lower() or "excel" in result["message"].lower()


def test_context_insight_toggle_not_enough_switches():
    """Too few switches should not trigger."""
    rule = ContextInsightRule(toggle_window_s=300, toggle_min_switches=10)
    result = None
    for app in ["a.exe", "b.exe", "a.exe"]:
        snap = StateSnapshot(process_exe=app, event_count=1)
        r = rule.check(snap)
        if r is not None:
            result = r
    assert result is None


def test_context_insight_dwell_triggers():
    """Staying in one app long enough triggers a dwell insight."""
    rule = ContextInsightRule(dwell_threshold_s=60)
    snap = StateSnapshot(process_exe="word.exe", event_count=1)
    # First call sets dwell start
    rule.check(snap)
    # Simulate time passing
    rule._dwell_start = time.time() - 120
    result = rule.check(snap)
    assert result is not None
    assert result["rule"] == "context_insight_dwell"
    assert "word" in result["message"].lower()


def test_context_insight_dwell_not_long_enough():
    """Short dwell should not trigger."""
    rule = ContextInsightRule(dwell_threshold_s=1800)
    snap = StateSnapshot(process_exe="word.exe", event_count=1)
    rule.check(snap)
    # Only 10 seconds — not enough
    result = rule.check(snap)
    assert result is None


def test_context_insight_dwell_no_repeat_notification():
    """Dwell notification should not fire twice for the same app."""
    rule = ContextInsightRule(dwell_threshold_s=60)
    snap = StateSnapshot(process_exe="word.exe", event_count=1)
    rule.check(snap)
    rule._dwell_start = time.time() - 120
    first = rule.check(snap)
    assert first is not None
    second = rule.check(snap)
    assert second is None


def test_context_insight_empty_process():
    """Empty process_exe should not trigger."""
    rule = ContextInsightRule()
    snap = StateSnapshot(process_exe="", event_count=1)
    result = rule.check(snap)
    assert result is None
