import asyncio
from datetime import datetime, timedelta, timezone

from app.schemas import WindowEvent
from app.state import StateStore


def test_state_store_record_and_read():
    store = StateStore(max_events=5)
    event = WindowEvent(
        hwnd="0x1",
        title="Test Window",
        process_exe="C:\\Test.exe",
        pid=123,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )

    asyncio.run(store.record(event))
    current = asyncio.run(store.current())
    assert current is not None
    assert current.title == "Test Window"
    assert asyncio.run(store.event_count()) == 1


def test_event_limit():
    store = StateStore(max_events=2)
    for idx in range(3):
        event = WindowEvent(
            hwnd=hex(idx),
            title=f"Window {idx}",
            process_exe="C:\\Test.exe",
            pid=100 + idx,
            timestamp=datetime.now(timezone.utc),
            source="test",
        )
        asyncio.run(store.record(event))

    events = asyncio.run(store.events())
    assert len(events) == 2
    assert events[-1].title == "Window 2"


def test_current_returns_copy_not_internal_reference():
    store = StateStore(max_events=5)
    event = WindowEvent(
        hwnd="0x2",
        title="Immutable Current",
        process_exe="C:\\Test.exe",
        pid=222,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(store.record(event))

    current = asyncio.run(store.current())
    assert current is not None
    current.title = "Mutated externally"

    current_again = asyncio.run(store.current())
    assert current_again is not None
    assert current_again.title == "Immutable Current"


def test_events_returns_copies_not_internal_references():
    store = StateStore(max_events=5)
    event = WindowEvent(
        hwnd="0x3",
        title="Immutable Event",
        process_exe="C:\\Test.exe",
        pid=333,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(store.record(event))

    events = asyncio.run(store.events())
    assert events
    events[0].title = "Mutated list entry"

    events_again = asyncio.run(store.events())
    assert events_again
    assert events_again[0].title == "Immutable Event"


def test_snapshot_returns_copies_not_internal_references():
    store = StateStore(max_events=5)
    event = WindowEvent(
        hwnd="0x4",
        title="Immutable Snapshot",
        process_exe="C:\\Test.exe",
        pid=444,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    asyncio.run(store.record(event))

    current, events = asyncio.run(store.snapshot())
    assert current is not None
    assert events
    current.title = "Mutated snapshot current"
    events[0].title = "Mutated snapshot event"

    current_again, events_again = asyncio.run(store.snapshot())
    assert current_again is not None
    assert events_again
    assert current_again.title == "Immutable Snapshot"
    assert events_again[0].title == "Immutable Snapshot"


def test_recent_switches_returns_within_window():
    """recent_switches returns only foreground events within the time window."""
    store = StateStore(max_events=20)
    now = datetime.now(timezone.utc)

    # Old event — 5 minutes ago, outside default 120s window
    old_event = WindowEvent(
        type="foreground",
        hwnd="0x10",
        title="Old App",
        process_exe="old.exe",
        pid=10,
        timestamp=now - timedelta(seconds=300),
        source="test",
    )
    # Recent event — 30 seconds ago, inside 120s window
    recent_event = WindowEvent(
        type="foreground",
        hwnd="0x11",
        title="Recent App",
        process_exe="recent.exe",
        pid=11,
        timestamp=now - timedelta(seconds=30),
        source="test",
    )
    # Very recent event — 5 seconds ago
    very_recent_event = WindowEvent(
        type="foreground",
        hwnd="0x12",
        title="Very Recent App",
        process_exe="veryrecent.exe",
        pid=12,
        timestamp=now - timedelta(seconds=5),
        source="test",
    )

    asyncio.run(store.record(old_event))
    asyncio.run(store.record(recent_event))
    asyncio.run(store.record(very_recent_event))

    switches = asyncio.run(store.recent_switches(since_s=120))
    assert len(switches) == 2
    # Should contain recent and very recent, not old
    titles = [s["title"] for s in switches]
    assert "Recent App" in titles
    assert "Very Recent App" in titles
    assert "Old App" not in titles
    # Each dict should have the expected keys
    for s in switches:
        assert "title" in s
        assert "process_exe" in s
        assert "timestamp" in s


def test_recent_switches_empty_when_no_events():
    """Empty store returns empty list from recent_switches."""
    store = StateStore(max_events=10)
    switches = asyncio.run(store.recent_switches(120))
    assert switches == []
