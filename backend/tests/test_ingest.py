"""Tests for collector ingest route helpers (pong watchdog, heartbeat sender)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.routes.ingest import _heartbeat_sender, _pong_watchdog


@pytest.mark.asyncio
async def test_pong_watchdog_closes_on_timeout():
    """Watchdog should close WS when no pong arrives within timeout."""
    ws = AsyncMock()
    # last_pong set to "long ago" so elapsed > timeout immediately
    last_pong = [asyncio.get_running_loop().time() - 100]

    await _pong_watchdog(ws, last_pong, timeout_s=0.05)
    ws.close.assert_awaited_once()
    _, kwargs = ws.close.call_args
    assert kwargs.get("code") == 1001


@pytest.mark.asyncio
async def test_pong_watchdog_resets_on_pong():
    """Watchdog should NOT close WS if last_pong is refreshed before timeout."""
    ws = AsyncMock()
    last_pong = [asyncio.get_running_loop().time()]

    async def keep_refreshing():
        for _ in range(5):
            await asyncio.sleep(0.02)
            last_pong[0] = asyncio.get_running_loop().time()

    refresh_task = asyncio.create_task(keep_refreshing())
    watchdog_task = asyncio.create_task(
        _pong_watchdog(ws, last_pong, timeout_s=0.08)
    )

    # Let refresh run, then cancel watchdog
    await refresh_task
    await asyncio.sleep(0.05)
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

    ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_sender_sends_pings():
    """Heartbeat sender should send JSON pings at the configured interval."""
    ws = AsyncMock()

    task = asyncio.create_task(_heartbeat_sender(ws, interval_s=0.05))
    await asyncio.sleep(0.18)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert ws.send_json.await_count >= 2
    for call in ws.send_json.call_args_list:
        assert call[0][0] == {"type": "ping"}
