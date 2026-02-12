"""SQLite persistence for events, autonomy runs, task records, and runtime settings."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from .schemas import AutonomyRunRecord, TaskRecord, WindowEvent

SCHEMA_VERSION = 1


def _is_memory_path(path: str) -> bool:
    value = (path or "").strip().lower()
    return value in {":memory:", "file::memory:"} or value.startswith("file::memory:")


def _is_uri_path(path: str) -> bool:
    return (path or "").strip().lower().startswith("file:")


def _filesystem_path_from_uri(path: str) -> Optional[str]:
    parsed = urlsplit(path)
    if parsed.scheme != "file":
        return None
    raw_path = unquote(parsed.path or "")
    if not raw_path:
        return None
    if raw_path.startswith(":memory:"):
        return None
    return raw_path


class EventDatabase:
    def __init__(
        self,
        path: str,
        retention_days: int,
        max_events: int,
        max_autonomy_runs: int = 0,
        autonomy_retention_days: int = 0,
        max_task_records: int = 0,
        task_retention_days: int = 0,
    ) -> None:
        self._path = path
        self._retention_days = retention_days
        self._max_events = max_events
        self._max_autonomy_runs = max_autonomy_runs
        self._autonomy_retention_days = autonomy_retention_days
        self._max_task_records = max_task_records
        self._task_retention_days = task_retention_days
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db_path = self._path
        uri_mode = _is_uri_path(db_path)

        if uri_mode:
            fs_path = _filesystem_path_from_uri(db_path)
            if fs_path:
                Path(fs_path).parent.mkdir(parents=True, exist_ok=True)
        elif not _is_memory_path(db_path):
            file_path = Path(db_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path, check_same_thread=False, uri=uri_mode)
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
                "CREATE INDEX IF NOT EXISTS idx_events_type_timestamp ON events(type, timestamp DESC)"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS autonomy_runs (
                    run_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_autonomy_runs_updated_at ON autonomy_runs(updated_at)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS task_records (
                    task_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_records_updated_at ON task_records(updated_at)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_settings_updated_at ON runtime_settings(updated_at)"
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
            event_id = int(cur.lastrowid or 0)
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
            cur.execute("DELETE FROM autonomy_runs")
            cur.execute("DELETE FROM task_records")
            cur.execute("DELETE FROM runtime_settings")
            self._conn.commit()

    async def set_runtime_setting(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_runtime_setting, key, value)

    def _set_runtime_setting(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO runtime_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
            self._conn.commit()

    async def get_runtime_setting(self, key: str) -> Optional[str]:
        return await asyncio.to_thread(self._get_runtime_setting, key)

    def _get_runtime_setting(self, key: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute(
                "SELECT value FROM runtime_settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return str(row["value"])

    async def delete_runtime_setting(self, key: str) -> None:
        await asyncio.to_thread(self._delete_runtime_setting, key)

    def _delete_runtime_setting(self, key: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM runtime_settings WHERE key = ?", (key,))
            self._conn.commit()

    async def upsert_autonomy_run(self, run: AutonomyRunRecord) -> None:
        await asyncio.to_thread(self._upsert_autonomy_run, run)

    def _upsert_autonomy_run(self, run: AutonomyRunRecord) -> None:
        payload = run.model_dump(mode="json")
        updated_at = payload.get("updated_at") or datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO autonomy_runs (run_id, updated_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (run.run_id, updated_at, json.dumps(payload)),
            )
            self._apply_autonomy_retention(cur)
            self._conn.commit()

    async def list_autonomy_runs(self, limit: int = 50) -> List[AutonomyRunRecord]:
        return await asyncio.to_thread(self._list_autonomy_runs, limit)

    def _list_autonomy_runs(self, limit: int) -> List[AutonomyRunRecord]:
        if limit <= 0:
            return []
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT payload_json
                FROM autonomy_runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items: List[AutonomyRunRecord] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            items.append(AutonomyRunRecord.model_validate(payload))
        return items

    async def recent_autonomy_outcomes(self, limit: int = 20) -> list[dict]:
        """Fetch recent terminal autonomy runs for promotion analysis."""
        return await asyncio.to_thread(self._recent_autonomy_outcomes, limit)

    def _recent_autonomy_outcomes(self, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT payload_json
                FROM autonomy_runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit * 2,),  # fetch extra to filter terminal statuses
            ).fetchall()
        results: list[dict] = []
        terminal = {"completed", "failed", "cancelled"}
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload.get("status") in terminal:
                results.append({
                    "autonomy_level": payload.get("autonomy_level", "supervised"),
                    "status": payload["status"],
                })
                if len(results) >= limit:
                    break
        return results

    async def upsert_task_record(self, task: TaskRecord) -> None:
        await asyncio.to_thread(self._upsert_task_record, task)

    def _upsert_task_record(self, task: TaskRecord) -> None:
        payload = task.model_dump(mode="json")
        updated_at = payload.get("updated_at") or datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO task_records (task_id, updated_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (task.task_id, updated_at, json.dumps(payload)),
            )
            self._apply_task_retention(cur)
            self._conn.commit()

    async def list_task_records(self, limit: int = 50) -> List[TaskRecord]:
        return await asyncio.to_thread(self._list_task_records, limit)

    def _list_task_records(self, limit: int) -> List[TaskRecord]:
        if limit <= 0:
            return []
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT payload_json
                FROM task_records
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items: List[TaskRecord] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            items.append(TaskRecord.model_validate(payload))
        return items

    def _apply_autonomy_retention(self, cur: sqlite3.Cursor) -> None:
        if self._autonomy_retention_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._autonomy_retention_days)
            cur.execute(
                "DELETE FROM autonomy_runs WHERE updated_at < ?",
                (cutoff.isoformat(),),
            )
        if self._max_autonomy_runs <= 0:
            return
        count_row = cur.execute("SELECT COUNT(*) AS count FROM autonomy_runs").fetchone()
        if not count_row or count_row["count"] <= self._max_autonomy_runs:
            return
        to_delete = count_row["count"] - self._max_autonomy_runs
        cur.execute(
            """
            DELETE FROM autonomy_runs
            WHERE run_id IN (
                SELECT run_id
                FROM autonomy_runs
                ORDER BY updated_at ASC, run_id ASC
                LIMIT ?
            )
            """,
            (to_delete,),
        )

    def _apply_task_retention(self, cur: sqlite3.Cursor) -> None:
        if self._task_retention_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._task_retention_days)
            cur.execute(
                "DELETE FROM task_records WHERE updated_at < ?",
                (cutoff.isoformat(),),
            )
        if self._max_task_records <= 0:
            return
        count_row = cur.execute("SELECT COUNT(*) AS count FROM task_records").fetchone()
        if not count_row or count_row["count"] <= self._max_task_records:
            return
        to_delete = count_row["count"] - self._max_task_records
        cur.execute(
            """
            DELETE FROM task_records
            WHERE task_id IN (
                SELECT task_id
                FROM task_records
                ORDER BY updated_at ASC, task_id ASC
                LIMIT ?
            )
            """,
            (to_delete,),
        )

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
            uia_json = json.dumps(event.uia.model_dump())
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
        return WindowEvent.model_validate(payload)

    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
