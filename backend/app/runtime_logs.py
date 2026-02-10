"""In-memory ring buffer for runtime log capture with filtering and correlation."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Optional


class RuntimeLogStore:
    def __init__(self, max_entries: int = 1000):
        self._entries = deque(maxlen=max(1, int(max_entries)))
        self._lock = Lock()

    def append(self, *, level: str, logger_name: str, message: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": logger_name,
            "message": message,
        }
        with self._lock:
            self._entries.append(entry)

    def list_entries(
        self,
        *,
        limit: int = 200,
        level: Optional[str] = None,
        contains: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> list[dict]:
        max_items = max(1, min(int(limit), 2000))
        level_filter = (level or "").strip().upper()
        contains_filter = (contains or "").strip().lower()
        since_dt = self._parse_iso(since)
        until_dt = self._parse_iso(until)
        with self._lock:
            items = list(self._entries)

        if level_filter:
            items = [item for item in items if (item.get("level") or "").upper() == level_filter]
        if contains_filter:
            items = [
                item
                for item in items
                if contains_filter in (item.get("message") or "").lower()
                or contains_filter in (item.get("logger") or "").lower()
            ]
        if since_dt:
            items = [item for item in items if self._entry_timestamp(item) >= since_dt]
        if until_dt:
            items = [item for item in items if self._entry_timestamp(item) <= until_dt]
        return items[-max_items:]

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def _parse_iso(self, value: Optional[str]) -> Optional[datetime]:
        raw = (value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _entry_timestamp(self, item: dict) -> datetime:
        parsed = self._parse_iso(item.get("timestamp"))
        if parsed is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return parsed


class RuntimeLogHandler(logging.Handler):
    def __init__(self, store: RuntimeLogStore):
        super().__init__()
        self._store = store

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._store.append(
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
            )
        except Exception:
            self.handleError(record)
