"""Tracks Windows collector WebSocket connection state and event statistics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class CollectorStatus:
    last_event_at: Optional[datetime] = None
    last_transport: Optional[str] = None  # ws|http
    last_source: Optional[str] = None
    ws_connected: bool = False
    ws_connected_at: Optional[datetime] = None
    ws_disconnected_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    total_events: int = 0
    uia_events: int = 0


class CollectorStatusStore:
    def __init__(self) -> None:
        self._s = CollectorStatus()
        self._lock = asyncio.Lock()

    async def note_ws_connected(self, now: datetime) -> None:
        async with self._lock:
            self._s.ws_connected = True
            self._s.ws_connected_at = now

    async def note_ws_disconnected(self, now: datetime) -> None:
        async with self._lock:
            self._s.ws_connected = False
            self._s.ws_disconnected_at = now
            self._s.last_heartbeat_at = None

    async def note_heartbeat(self, now: datetime) -> None:
        async with self._lock:
            self._s.last_heartbeat_at = now

    async def note_event(self, now: datetime, *, transport: str, source: str, has_uia: bool) -> None:
        async with self._lock:
            self._s.last_event_at = now
            self._s.last_transport = transport
            self._s.last_source = source
            self._s.total_events += 1
            if has_uia:
                self._s.uia_events += 1

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            s = self._s
            return {
                "ws_connected": s.ws_connected,
                "ws_connected_at": s.ws_connected_at.isoformat() if s.ws_connected_at else None,
                "ws_disconnected_at": s.ws_disconnected_at.isoformat() if s.ws_disconnected_at else None,
                "last_heartbeat_at": s.last_heartbeat_at.isoformat() if s.last_heartbeat_at else None,
                "last_event_at": s.last_event_at.isoformat() if s.last_event_at else None,
                "last_transport": s.last_transport,
                "last_source": s.last_source,
                "total_events": s.total_events,
                "uia_events": s.uia_events,
            }
