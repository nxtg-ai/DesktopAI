import asyncio
from datetime import datetime, timezone

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
