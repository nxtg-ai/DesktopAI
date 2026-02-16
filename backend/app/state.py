"""In-memory event store with current window state, idle tracking, and snapshots."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from .schemas import WindowEvent

_SESSION_WINDOW_S = 1800  # 30-minute rolling window


class StateStore:
    def __init__(self, max_events: int) -> None:
        self._events: Deque[WindowEvent] = deque(maxlen=max_events)
        self._current: Optional[WindowEvent] = None
        self._idle: bool = False
        self._idle_since: Optional[datetime] = None
        self._lock = asyncio.Lock()
        # Session tracking: list of (timestamp, process_exe) for foreground switches
        self._fg_switches: List[tuple[datetime, str]] = []
        self._session_start: Optional[datetime] = None

    async def record(self, event: WindowEvent) -> None:
        snapshot = self._clone_event(event)
        async with self._lock:
            self._events.append(snapshot)
            if snapshot.type == "foreground":
                self._current = snapshot
                self._fg_switches.append(
                    (snapshot.timestamp, snapshot.process_exe or "")
                )
                if self._session_start is None:
                    self._session_start = snapshot.timestamp
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

    async def recent_switches(self, since_s: int = 120) -> List[Dict[str, Any]]:
        """Return raw foreground switch events from the last ``since_s`` seconds.

        Each dict has ``title``, ``process_exe``, and ``timestamp``.
        No deduplication — every foreground event within the window is returned.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - since_s
        async with self._lock:
            result: List[Dict[str, Any]] = []
            for event in reversed(self._events):
                if event.type != "foreground":
                    continue
                if event.timestamp.timestamp() < cutoff:
                    continue
                result.append({
                    "title": event.title,
                    "process_exe": event.process_exe,
                    "timestamp": event.timestamp.isoformat(),
                })
            return result

    async def session_summary(self) -> Dict[str, Any]:
        async with self._lock:
            return self._compute_session_summary()

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
            self._fg_switches.clear()
            self._session_start = None

    def _compute_session_summary(self) -> Dict[str, Any]:
        """Build a session summary from recent foreground switches (no lock)."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - _SESSION_WINDOW_S

        # Prune old switches
        self._fg_switches = [
            (ts, exe) for ts, exe in self._fg_switches if ts.timestamp() > cutoff
        ]

        switches = self._fg_switches
        if not switches:
            return {
                "app_switches": 0,
                "unique_apps": 0,
                "top_apps": [],
                "session_duration_s": 0,
            }

        # Dwell time: time between consecutive switches attributed to the earlier app
        dwell: Dict[str, float] = {}
        for i in range(len(switches) - 1):
            exe = switches[i][1]
            dt = (switches[i + 1][0] - switches[i][0]).total_seconds()
            dwell[exe] = dwell.get(exe, 0.0) + dt
        # Current app gets dwell from last switch to now
        last_exe = switches[-1][1]
        dwell[last_exe] = dwell.get(last_exe, 0.0) + (
            now - switches[-1][0]
        ).total_seconds()

        # Sort by dwell descending, top 5
        top_apps = sorted(dwell.items(), key=lambda x: x[1], reverse=True)[:5]

        session_duration = 0.0
        if self._session_start:
            session_duration = (now - self._session_start).total_seconds()

        return {
            "app_switches": len(switches),
            "unique_apps": len(dwell),
            "top_apps": [
                {"process": exe, "dwell_s": round(s, 1)} for exe, s in top_apps
            ],
            "session_duration_s": round(session_duration, 1),
        }

    def _clone_event(self, event: WindowEvent) -> WindowEvent:
        return event.model_copy(deep=True)
