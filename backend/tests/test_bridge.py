from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from app.bridge import CommandBridge


@pytest.fixture
def bridge():
    return CommandBridge(default_timeout_s=2.0)


def test_not_connected_by_default(bridge):
    assert not bridge.connected
    assert bridge.status()["connected"] is False


@pytest.mark.asyncio
async def test_not_connected_raises(bridge):
    with pytest.raises(RuntimeError, match="not connected"):
        await bridge.execute("observe")


@pytest.mark.asyncio
async def test_attach_detach_lifecycle(bridge):
    ws = AsyncMock()
    bridge.attach(ws)
    assert bridge.connected

    bridge.detach()
    assert not bridge.connected


@pytest.mark.asyncio
async def test_execute_and_handle_result(bridge):
    ws = AsyncMock()
    bridge.attach(ws)

    async def simulate_result():
        await asyncio.sleep(0.01)
        call_args = ws.send_json.call_args
        command = call_args[0][0]
        bridge.handle_result({
            "type": "command_result",
            "command_id": command["command_id"],
            "ok": True,
            "result": {"action": "observe"},
        })

    task = asyncio.create_task(simulate_result())
    result = await bridge.execute("observe", timeout_s=2.0)
    await task

    assert result["ok"] is True
    assert result["result"]["action"] == "observe"


@pytest.mark.asyncio
async def test_timeout_raises(bridge):
    ws = AsyncMock()
    bridge.attach(ws)

    with pytest.raises(asyncio.TimeoutError):
        await bridge.execute("observe", timeout_s=0.05)


@pytest.mark.asyncio
async def test_detach_cancels_pending(bridge):
    ws = AsyncMock()
    bridge.attach(ws)

    async def detach_soon():
        await asyncio.sleep(0.01)
        bridge.detach()

    task = asyncio.create_task(detach_soon())

    with pytest.raises((asyncio.CancelledError, asyncio.TimeoutError)):
        await bridge.execute("observe", timeout_s=2.0)

    await task
    assert len(bridge._pending) == 0


@pytest.mark.asyncio
async def test_handle_result_unknown_command(bridge):
    result = bridge.handle_result({"command_id": "unknown-id", "ok": True})
    assert result is False


@pytest.mark.asyncio
async def test_send_failure_raises(bridge):
    ws = AsyncMock()
    ws.send_json.side_effect = Exception("connection lost")
    bridge.attach(ws)

    with pytest.raises(RuntimeError, match="failed to send"):
        await bridge.execute("observe")


@pytest.mark.asyncio
async def test_stale_detach_ignored(bridge):
    """Detaching an old WS after a new one has attached should be a no-op."""
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    bridge.attach(ws1)
    bridge.attach(ws2)  # simulate reconnect

    bridge.detach(ws1)  # stale detach — should be ignored
    assert bridge.connected  # ws2 still live


@pytest.mark.asyncio
async def test_matching_detach_works(bridge):
    """Detaching the current WS should disconnect the bridge."""
    ws1 = AsyncMock()
    bridge.attach(ws1)

    bridge.detach(ws1)
    assert not bridge.connected
