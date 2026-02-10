"""Tests for WebSocketHub connection limits and broadcast."""

from unittest.mock import AsyncMock

import pytest
from app.ws import WebSocketHub


def _mock_ws():
    """Create a mock WebSocket with accept/close/send_json methods."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_add_accepts_websocket():
    hub = WebSocketHub(max_connections=5)
    ws = _mock_ws()
    result = await hub.add(ws)
    assert result is True
    ws.accept.assert_awaited_once()
    assert hub.connection_count == 1


@pytest.mark.asyncio
async def test_add_rejects_at_capacity():
    hub = WebSocketHub(max_connections=2)
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    ws3 = _mock_ws()

    assert await hub.add(ws1) is True
    assert await hub.add(ws2) is True
    assert hub.connection_count == 2

    # Third connection should be rejected
    result = await hub.add(ws3)
    assert result is False
    ws3.close.assert_awaited_once_with(code=1013, reason="max connections reached")
    ws3.accept.assert_not_awaited()
    assert hub.connection_count == 2


@pytest.mark.asyncio
async def test_remove_decreases_count():
    hub = WebSocketHub(max_connections=5)
    ws = _mock_ws()
    await hub.add(ws)
    assert hub.connection_count == 1
    await hub.remove(ws)
    assert hub.connection_count == 0


@pytest.mark.asyncio
async def test_remove_allows_new_connection_after_disconnect():
    hub = WebSocketHub(max_connections=1)
    ws1 = _mock_ws()
    ws2 = _mock_ws()

    assert await hub.add(ws1) is True
    assert await hub.add(ws2) is False  # at capacity

    await hub.remove(ws1)
    assert await hub.add(ws2) is True  # slot freed


@pytest.mark.asyncio
async def test_broadcast_sends_to_all_clients():
    hub = WebSocketHub(max_connections=5)
    ws1 = _mock_ws()
    ws2 = _mock_ws()
    await hub.add(ws1)
    await hub.add(ws2)

    await hub.broadcast_json({"type": "test"})
    ws1.send_json.assert_awaited_once_with({"type": "test"})
    ws2.send_json.assert_awaited_once_with({"type": "test"})


@pytest.mark.asyncio
async def test_broadcast_removes_stale_clients():
    hub = WebSocketHub(max_connections=5)
    ws_good = _mock_ws()
    ws_bad = _mock_ws()
    ws_bad.send_json.side_effect = Exception("connection closed")

    await hub.add(ws_good)
    await hub.add(ws_bad)
    assert hub.connection_count == 2

    await hub.broadcast_json({"type": "test"})
    assert hub.connection_count == 1


@pytest.mark.asyncio
async def test_connection_count_property():
    hub = WebSocketHub(max_connections=10)
    assert hub.connection_count == 0

    sockets = []
    for _ in range(3):
        ws = _mock_ws()
        await hub.add(ws)
        sockets.append(ws)
    assert hub.connection_count == 3
