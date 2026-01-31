from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Deque, List, Optional

from .schemas import WindowEvent


class StateStore:
    def __init__(self, max_events: int) -> None:
        self._events: Deque[WindowEvent] = deque(maxlen=max_events)
        self._current: Optional[WindowEvent] = None
        self._idle: bool = False
        self._idle_since: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def record(self, event: WindowEvent) -> None:
        async with self._lock:
            self._events.append(event)
            if event.type == "foreground":
                self._current = event
            elif event.type == "idle":
                self._idle = True
                self._idle_since = event.timestamp
            elif event.type == "active":
                self._idle = False
                self._idle_since = None

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

    async def idle_state(self) -> tuple[bool, Optional[datetime]]:
        async with self._lock:
            return self._idle, self._idle_since

    async def hydrate(
        self,
        events: List[WindowEvent],
        current: Optional[WindowEvent],
        idle: bool,
        idle_since: Optional[datetime],
    ) -> None:
        async with self._lock:
            self._events.clear()
            maxlen = self._events.maxlen
            if maxlen is not None:
                events = events[-maxlen:]
            self._events.extend(events)
            self._current = current
            self._idle = idle
            self._idle_since = idle_since

    async def reset(self) -> None:
        async with self._lock:
            self._events.clear()
            self._current = None
            self._idle = False
            self._idle_since = None
