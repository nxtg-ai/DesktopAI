from __future__ import annotations

import asyncio
from collections import deque
from typing import Deque, List, Optional

from .schemas import WindowEvent


class StateStore:
    def __init__(self, max_events: int) -> None:
        self._events: Deque[WindowEvent] = deque(maxlen=max_events)
        self._current: Optional[WindowEvent] = None
        self._lock = asyncio.Lock()

    async def record(self, event: WindowEvent) -> None:
        async with self._lock:
            self._current = event
            self._events.append(event)

    async def snapshot(self) -> tuple[Optional[WindowEvent], List[WindowEvent]]:
        async with self._lock:
            current = self._current
            events = list(self._events)
        return current, events

    async def current(self) -> Optional[WindowEvent]:
        async with self._lock:
            return self._current

    async def events(self, limit: int | None = None) -> List[WindowEvent]:
        async with self._lock:
            items = list(self._events)
        if limit is None:
            return items
        if limit <= 0:
            return []
        return items[-limit:]

    async def event_count(self) -> int:
        async with self._lock:
            return len(self._events)
