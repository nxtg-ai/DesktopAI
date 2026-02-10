"""WebSocket hub for broadcasting real-time events to connected UI clients."""

from __future__ import annotations

import asyncio
from typing import Set

from fastapi import WebSocket


class WebSocketHub:
    def __init__(self, send_timeout_s: float = 1.0, max_connections: int = 50) -> None:
        self._clients: Set[WebSocket] = set()
        self._send_timeout_s = send_timeout_s
        self._max_connections = max_connections
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._clients)

    async def add(self, ws: WebSocket) -> bool:
        """Accept and register a WebSocket. Returns False if at capacity."""
        async with self._lock:
            if len(self._clients) >= self._max_connections:
                await ws.close(code=1013, reason="max connections reached")
                return False
            await ws.accept()
            self._clients.add(ws)
            return True

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast_json(self, payload: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return
        stale = []

        async def _send_one(ws: WebSocket):
            try:
                await asyncio.wait_for(ws.send_json(payload), timeout=self._send_timeout_s)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*[_send_one(ws) for ws in clients], return_exceptions=False)
        stale.extend(ws for ws in results if ws is not None)
        if stale:
            async with self._lock:
                for ws in stale:
                    self._clients.discard(ws)
