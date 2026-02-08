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
        snapshot = self._clone_event(event)
        async with self._lock:
            self._events.append(snapshot)
            if snapshot.type == "foreground":
                self._current = snapshot
            elif snapshot.type == "idle":
                self._idle = True
                self._idle_since = snapshot.timestamp
            elif snapshot.type == "active":
                self._idle = False
                self._idle_since = None

    async def snapshot(self) -> tuple[Optional[WindowEvent], List[WindowEvent]]:
        async with self._lock:
            current = self._clone_event(self._current) if self._current is not None else None
            events = [self._clone_event(event) for event in self._events]
        return current, events

    async def current(self) -> Optional[WindowEvent]:
        async with self._lock:
            if self._current is None:
                return None
            return self._clone_event(self._current)

    async def events(self, limit: int | None = None) -> List[WindowEvent]:
        async with self._lock:
            items = [self._clone_event(event) for event in self._events]
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
            self._events.extend(self._clone_event(event) for event in events)
            self._current = self._clone_event(current) if current is not None else None
            self._idle = idle
            self._idle_since = idle_since

    async def reset(self) -> None:
        async with self._lock:
            self._events.clear()
            self._current = None
            self._idle = False
            self._idle_since = None

    def _clone_event(self, event: WindowEvent) -> WindowEvent:
        if hasattr(event, "model_copy"):
            return event.model_copy(deep=True)
        return event.copy(deep=True)
