import asyncio
from datetime import datetime, timezone

from app.db import EventDatabase
from app.schemas import WindowEvent


def test_db_persists_events(tmp_path):
    db_path = tmp_path / "events.db"
    db = EventDatabase(str(db_path), retention_days=0, max_events=0)
    event = WindowEvent(
        type="foreground",
        hwnd="0x1",
        title="Docs",
        process_exe="C:\\Docs.exe",
        pid=101,
        timestamp=datetime.now(timezone.utc),
        source="test",
        category="docs",
    )
    asyncio.run(db.record_event(event))

    current, events, idle, idle_since = asyncio.run(db.load_snapshot(limit=10))
    assert len(events) == 1
    assert current is not None
    assert current.title == "Docs"
    assert idle is False
    assert idle_since is None
