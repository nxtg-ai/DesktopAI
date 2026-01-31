from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .schemas import WindowEvent

SCHEMA_VERSION = 1


class EventDatabase:
    def __init__(self, path: str, retention_days: int, max_events: int) -> None:
        self._path = path
        self._retention_days = retention_days
        self._max_events = max_events
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._path not in {":memory:", "file::memory:"}:
            db_path = Path(self._path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = cur.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                cur.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported DB schema version {row['version']} (expected {SCHEMA_VERSION})"
                )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    hwnd TEXT NOT NULL,
                    title TEXT NOT NULL,
                    process_exe TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    idle_ms INTEGER,
                    category TEXT,
                    uia_json TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.commit()

    async def record_event(self, event: WindowEvent) -> int:
        return await asyncio.to_thread(self._record_event, event)

    def _record_event(self, event: WindowEvent) -> int:
        payload = self._event_to_row(event)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO events (
                    type, hwnd, title, process_exe, pid, timestamp, source,
                    idle_ms, category, uia_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["type"],
                    payload["hwnd"],
                    payload["title"],
                    payload["process_exe"],
                    payload["pid"],
                    payload["timestamp"],
                    payload["source"],
                    payload["idle_ms"],
                    payload["category"],
                    payload["uia_json"],
                ),
            )
            event_id = int(cur.lastrowid)
            if event.type == "foreground":
                self._set_state(cur, "current_event_id", str(event_id))
                if event.category:
                    self._set_state(cur, "current_category", event.category)
            if event.type == "idle":
                self._set_state(cur, "idle", "1")
                self._set_state(cur, "idle_since", payload["timestamp"])
            elif event.type == "active":
                self._set_state(cur, "idle", "0")
                self._set_state(cur, "idle_since", "")
            self._apply_retention(cur)
            self._conn.commit()
            return event_id

    async def load_snapshot(
        self, limit: int
    ) -> Tuple[Optional[WindowEvent], List[WindowEvent], bool, Optional[datetime]]:
        return await asyncio.to_thread(self._load_snapshot, limit)

    def _load_snapshot(
        self, limit: int
    ) -> Tuple[Optional[WindowEvent], List[WindowEvent], bool, Optional[datetime]]:
        with self._lock:
            events = self._fetch_recent(limit)
            state = self._fetch_state()
            current = None
            current_id = state.get("current_event_id")
            if current_id:
                current = self._fetch_event_by_id(int(current_id))
            if current is None:
                current = self._fetch_last_foreground()
            idle = state.get("idle") == "1"
            idle_since = self._parse_datetime(state.get("idle_since"))
        return current, events, idle, idle_since

    async def clear(self) -> None:
        await asyncio.to_thread(self._clear)

    def _clear(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM events")
            cur.execute("DELETE FROM state")
            self._conn.commit()

    def _fetch_recent(self, limit: int) -> List[WindowEvent]:
        if limit <= 0:
            return []
        cur = self._conn.cursor()
        rows = cur.execute(
            """
            SELECT type, hwnd, title, process_exe, pid, timestamp, source,
                   idle_ms, category, uia_json
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    def _fetch_event_by_id(self, event_id: int) -> Optional[WindowEvent]:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT type, hwnd, title, process_exe, pid, timestamp, source,
                   idle_ms, category, uia_json
            FROM events
            WHERE id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    def _fetch_last_foreground(self) -> Optional[WindowEvent]:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT type, hwnd, title, process_exe, pid, timestamp, source,
                   idle_ms, category, uia_json
            FROM events
            WHERE type = 'foreground'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    def _fetch_state(self) -> dict:
        cur = self._conn.cursor()
        rows = cur.execute("SELECT key, value FROM state").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _set_state(self, cur: sqlite3.Cursor, key: str, value: str) -> None:
        cur.execute(
            """
            INSERT INTO state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )

    def _apply_retention(self, cur: sqlite3.Cursor) -> None:
        if self._retention_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
            cutoff_str = cutoff.isoformat()
            cur.execute("DELETE FROM events WHERE timestamp < ?", (cutoff_str,))
        if self._max_events > 0:
            count_row = cur.execute("SELECT COUNT(*) AS count FROM events").fetchone()
            if count_row and count_row["count"] > self._max_events:
                to_delete = count_row["count"] - self._max_events
                cur.execute(
                    "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                    (to_delete,),
                )

    def _event_to_row(self, event: WindowEvent) -> dict:
        timestamp = event.timestamp
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        uia_json = None
        if event.uia is not None:
            if hasattr(event.uia, "model_dump"):
                uia_json = json.dumps(event.uia.model_dump())
            else:
                uia_json = json.dumps(event.uia.dict())
        return {
            "type": event.type,
            "hwnd": event.hwnd,
            "title": event.title,
            "process_exe": event.process_exe,
            "pid": event.pid,
            "timestamp": timestamp,
            "source": event.source,
            "idle_ms": event.idle_ms,
            "category": event.category,
            "uia_json": uia_json,
        }

    def _row_to_event(self, row: sqlite3.Row) -> WindowEvent:
        payload = {
            "type": row["type"],
            "hwnd": row["hwnd"],
            "title": row["title"],
            "process_exe": row["process_exe"],
            "pid": row["pid"],
            "timestamp": row["timestamp"],
            "source": row["source"],
            "idle_ms": row["idle_ms"],
            "category": row["category"],
        }
        if row["uia_json"]:
            payload["uia"] = json.loads(row["uia_json"])
        if hasattr(WindowEvent, "model_validate"):
            return WindowEvent.model_validate(payload)
        return WindowEvent.parse_obj(payload)

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
