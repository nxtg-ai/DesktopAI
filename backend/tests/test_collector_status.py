"""Tests for CollectorStatusStore."""

from datetime import datetime, timezone

import pytest
from app.collector_status import CollectorStatusStore


@pytest.fixture
def status_store():
    return CollectorStatusStore()


@pytest.mark.asyncio
async def test_initial_snapshot(status_store):
    snap = await status_store.snapshot()
    assert snap["ws_connected"] is False
    assert snap["total_events"] == 0
    assert snap["uia_events"] == 0
    assert snap["last_event_at"] is None


@pytest.mark.asyncio
async def test_ws_connect_disconnect(status_store):
    now = datetime.now(timezone.utc)
    await status_store.note_ws_connected(now)
    snap = await status_store.snapshot()
    assert snap["ws_connected"] is True
    assert snap["ws_connected_at"] == now.isoformat()

    later = datetime.now(timezone.utc)
    await status_store.note_ws_disconnected(later)
    snap = await status_store.snapshot()
    assert snap["ws_connected"] is False
    assert snap["ws_disconnected_at"] == later.isoformat()


@pytest.mark.asyncio
async def test_note_event(status_store):
    now = datetime.now(timezone.utc)
    await status_store.note_event(now, transport="ws", source="test", has_uia=False)
    snap = await status_store.snapshot()
    assert snap["total_events"] == 1
    assert snap["uia_events"] == 0
    assert snap["last_transport"] == "ws"
    assert snap["last_source"] == "test"


@pytest.mark.asyncio
async def test_note_event_with_uia(status_store):
    now = datetime.now(timezone.utc)
    await status_store.note_event(now, transport="ws", source="test", has_uia=True)
    snap = await status_store.snapshot()
    assert snap["total_events"] == 1
    assert snap["uia_events"] == 1


@pytest.mark.asyncio
async def test_event_count_accumulates(status_store):
    now = datetime.now(timezone.utc)
    for i in range(5):
        await status_store.note_event(now, transport="http", source=f"src-{i}", has_uia=(i % 2 == 0))
    snap = await status_store.snapshot()
    assert snap["total_events"] == 5
    assert snap["uia_events"] == 3  # 0, 2, 4
    assert snap["last_source"] == "src-4"


@pytest.mark.asyncio
async def test_heartbeat_tracked(status_store):
    now = datetime.now(timezone.utc)
    await status_store.note_heartbeat(now)
    snap = await status_store.snapshot()
    assert snap["last_heartbeat_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_disconnect_clears_heartbeat(status_store):
    now = datetime.now(timezone.utc)
    await status_store.note_ws_connected(now)
    await status_store.note_heartbeat(now)
    snap = await status_store.snapshot()
    assert snap["last_heartbeat_at"] is not None

    later = datetime.now(timezone.utc)
    await status_store.note_ws_disconnected(later)
    snap = await status_store.snapshot()
    assert snap["last_heartbeat_at"] is None


@pytest.mark.asyncio
async def test_initial_snapshot_has_heartbeat_field(status_store):
    snap = await status_store.snapshot()
    assert "last_heartbeat_at" in snap
    assert snap["last_heartbeat_at"] is None
