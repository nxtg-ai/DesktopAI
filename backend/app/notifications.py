"""SQLite-backed notification store for proactive alerts."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class NotificationStore:
    """Persistent notification storage following the TrajectoryStore pattern."""

    def __init__(self, path: str, max_notifications: int = 200) -> None:
        self._path = path
        self._max_notifications = max_notifications
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db_path = self._path
        is_memory = db_path.strip().lower() in {":memory:", "file::memory:"}

        if not is_memory:
            file_path = Path(db_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT,
                    expires_at TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_created "
                "ON notifications(created_at DESC)"
            )
            self._conn.commit()

    # ── Async wrappers ────────────────────────────────────────────────────

    async def create(
        self,
        type: str,
        title: str,
        message: str,
        rule: str,
        expires_at: Optional[str] = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._create, type, title, message, rule, expires_at
        )

    async def list_notifications(
        self, unread_only: bool = False, limit: int = 50
    ) -> List[dict]:
        return await asyncio.to_thread(self._list_notifications, unread_only, limit)

    async def mark_read(self, notification_id: str) -> bool:
        return await asyncio.to_thread(self._mark_read, notification_id)

    async def delete(self, notification_id: str) -> bool:
        return await asyncio.to_thread(self._delete, notification_id)

    async def unread_count(self) -> int:
        return await asyncio.to_thread(self._unread_count)

    # ── Sync implementations ─────────────────────────────────────────────

    def _create(
        self,
        type: str,
        title: str,
        message: str,
        rule: str,
        expires_at: Optional[str] = None,
    ) -> dict:
        notification_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO notifications "
                "(notification_id, type, title, message, rule, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (notification_id, type, title, message, rule, now, expires_at),
            )
            self._apply_retention(cur)
            self._conn.commit()

        return {
            "notification_id": notification_id,
            "type": type,
            "title": title,
            "message": message,
            "rule": rule,
            "created_at": now,
            "read_at": None,
            "expires_at": expires_at,
        }

    def _list_notifications(self, unread_only: bool, limit: int) -> List[dict]:
        if limit <= 0:
            return []
        with self._lock:
            # Clean expired first
            self._clean_expired()
            if unread_only:
                rows = self._conn.execute(
                    "SELECT * FROM notifications WHERE read_at IS NULL "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def _mark_read(self, notification_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE notifications SET read_at = ? WHERE notification_id = ? AND read_at IS NULL",
                (now, notification_id),
            )
            updated = cur.rowcount > 0
            self._conn.commit()
        return updated

    def _delete(self, notification_id: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "DELETE FROM notifications WHERE notification_id = ?",
                (notification_id,),
            )
            deleted = cur.rowcount > 0
            self._conn.commit()
        return deleted

    def _unread_count(self) -> int:
        with self._lock:
            self._clean_expired()
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM notifications WHERE read_at IS NULL"
            ).fetchone()
        return row["count"] if row else 0

    def _clean_expired(self) -> None:
        """Remove expired notifications (caller must hold lock)."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "DELETE FROM notifications WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )

    def _apply_retention(self, cur: sqlite3.Cursor) -> None:
        if self._max_notifications <= 0:
            return
        count_row = cur.execute(
            "SELECT COUNT(*) AS count FROM notifications"
        ).fetchone()
        if not count_row or count_row["count"] <= self._max_notifications:
            return
        to_delete = count_row["count"] - self._max_notifications
        cur.execute(
            """
            DELETE FROM notifications WHERE notification_id IN (
                SELECT notification_id FROM notifications
                ORDER BY created_at ASC LIMIT ?
            )
            """,
            (to_delete,),
        )
