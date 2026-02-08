import asyncio
import time

from app.ws import WebSocketHub


class _FakeWebSocket:
    def __init__(self, *, block_send: bool = False) -> None:
        self.accepted = False
        self.block_send = block_send
        self.payloads = []
        self.send_calls = 0
        self._block_event = asyncio.Event()

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.send_calls += 1
        if self.block_send:
            await self._block_event.wait()
        self.payloads.append(payload)


def test_broadcast_does_not_block_on_slow_client():
    async def scenario():
        hub = WebSocketHub(send_timeout_s=0.05)
        fast = _FakeWebSocket()
        slow = _FakeWebSocket(block_send=True)

        await hub.add(fast)
        await hub.add(slow)

        payload = {"type": "event", "n": 1}
        start = time.perf_counter()
        await hub.broadcast_json(payload)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.2
        assert fast.payloads == [payload]

        # Slow websocket should be removed after timeout.
        assert slow.send_calls == 1
        await hub.broadcast_json({"type": "event", "n": 2})
        assert slow.send_calls == 1

    asyncio.run(scenario())
