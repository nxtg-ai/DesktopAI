import asyncio
from datetime import datetime, timezone

from app.state import StateStore
from app.schemas import WindowEvent


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
