"""SQLite-backed conversation memory for multi-turn chat."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ChatMemoryStore:
    """Persistent conversation history following the TrajectoryStore pattern."""

    def __init__(
        self,
        path: str,
        max_conversations: int = 50,
        max_messages_per_conversation: int = 100,
    ) -> None:
        self._path = path
        self._max_conversations = max_conversations
        self._max_messages = max_messages_per_conversation
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
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    desktop_context_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
                "ON messages(conversation_id, created_at)"
            )
            self._conn.commit()

    # ── Async wrappers ────────────────────────────────────────────────────

    async def create_conversation(self, title: str = "") -> str:
        return await asyncio.to_thread(self._create_conversation, title)

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        desktop_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        return await asyncio.to_thread(
            self._save_message, conversation_id, role, content, desktop_context
        )

    async def get_messages(
        self, conversation_id: str, limit: int = 20
    ) -> List[dict]:
        return await asyncio.to_thread(self._get_messages, conversation_id, limit)

    async def list_conversations(self, limit: int = 20) -> List[dict]:
        return await asyncio.to_thread(self._list_conversations, limit)

    async def get_conversation(self, conversation_id: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_conversation, conversation_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        return await asyncio.to_thread(self._delete_conversation, conversation_id)

    # ── Sync implementations ─────────────────────────────────────────────

    def _create_conversation(self, title: str = "") -> str:
        conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (conversation_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now),
            )
            self._conn.commit()
        return conversation_id

    def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        desktop_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        ctx_json = json.dumps(desktop_context) if desktop_context else None

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO messages (message_id, conversation_id, role, content, "
                "desktop_context_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, ctx_json, now),
            )
            cur.execute(
                "UPDATE conversations SET updated_at = ?, "
                "message_count = (SELECT COUNT(*) FROM messages WHERE conversation_id = ?) "
                "WHERE conversation_id = ?",
                (now, conversation_id, conversation_id),
            )
            self._apply_message_retention(cur, conversation_id)
            self._apply_retention(cur)
            self._conn.commit()
        return message_id

    def _get_messages(self, conversation_id: str, limit: int) -> List[dict]:
        if limit <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT message_id, conversation_id, role, content, "
                "desktop_context_json, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def _list_conversations(self, limit: int) -> List[dict]:
        if limit <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT conversation_id, title, created_at, updated_at, message_count "
                "FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_conversation(self, conversation_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT conversation_id, title, created_at, updated_at, message_count "
                "FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def _delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            cur.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            deleted = cur.rowcount > 0
            self._conn.commit()
        return deleted

    def _apply_message_retention(
        self, cur: sqlite3.Cursor, conversation_id: str
    ) -> None:
        if self._max_messages <= 0:
            return
        count_row = cur.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if not count_row or count_row["count"] <= self._max_messages:
            return
        to_delete = count_row["count"] - self._max_messages
        cur.execute(
            """
            DELETE FROM messages WHERE message_id IN (
                SELECT message_id FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC LIMIT ?
            )
            """,
            (conversation_id, to_delete),
        )

    def _apply_retention(self, cur: sqlite3.Cursor) -> None:
        if self._max_conversations <= 0:
            return
        count_row = cur.execute(
            "SELECT COUNT(*) AS count FROM conversations"
        ).fetchone()
        if not count_row or count_row["count"] <= self._max_conversations:
            return
        to_delete = count_row["count"] - self._max_conversations
        # Get the oldest conversation IDs
        old_ids = cur.execute(
            "SELECT conversation_id FROM conversations "
            "ORDER BY updated_at ASC LIMIT ?",
            (to_delete,),
        ).fetchall()
        for row in old_ids:
            cid = row["conversation_id"]
            cur.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
            cur.execute(
                "DELETE FROM conversations WHERE conversation_id = ?", (cid,)
            )

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict:
        ctx_json = row["desktop_context_json"]
        desktop_context = None
        if ctx_json:
            try:
                desktop_context = json.loads(ctx_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "message_id": row["message_id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "desktop_context": desktop_context,
            "created_at": row["created_at"],
        }
