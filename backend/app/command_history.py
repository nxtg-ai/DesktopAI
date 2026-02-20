"""Command history with undo support."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _compute_undo(
    action: str, params: dict[str, Any], prev_window: str | None = None
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Return (reversible, undo_action, undo_params) for a given action.

    Args:
        action: The direct bridge action name.
        params: The action parameters dict.
        prev_window: Title of the foreground window before the action fired.

    Returns:
        Tuple of (reversible, undo_action, undo_params). When reversible is
        False the remaining fields are None.
    """
    if action == "open_application":
        # Cannot reliably close — Alt+F4 could hit the wrong window.
        return False, None, None
    if action == "focus_window" and prev_window:
        return True, "focus_window", {"title": prev_window}
    if action == "type_text":
        return True, "send_keys", {"keys": "ctrl+z"}
    if action == "_type_in_window":
        window = params.get("window", "")
        if window:
            return True, "_undo_type_in_window", {"window": window}
        return True, "send_keys", {"keys": "ctrl+z"}
    if action == "scroll":
        direction = params.get("direction", "down")
        amount = params.get("amount", 3)
        opposite = "up" if direction == "down" else "down"
        return True, "scroll", {"direction": opposite, "amount": amount}
    if action == "_scroll_in_window":
        direction = params.get("direction", "down")
        amount = params.get("amount", 3)
        opposite = "up" if direction == "down" else "down"
        return True, "_scroll_in_window", {
            "window": params.get("window", ""),
            "direction": opposite,
            "amount": amount,
        }
    # click, double_click, right_click, send_keys — not reversible
    return False, None, None


class CommandHistoryStore:
    """SQLite-backed command history with undo support.

    Follows the same threading.Lock + asyncio.to_thread + WAL mode pattern
    used by ChatMemoryStore and TrajectoryStore.
    """

    def __init__(self, path: str = "command_history.db", max_entries: int = 500) -> None:
        self._path = path
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._conn = self._connect()

    def _connect(self) -> sqlite3.Connection:
        if not self._path.strip().lower().startswith(":"):
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_history (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                parameters TEXT NOT NULL,
                result TEXT,
                reversible INTEGER NOT NULL DEFAULT 0,
                undo_action TEXT,
                undo_parameters TEXT,
                undone INTEGER NOT NULL DEFAULT 0,
                conversation_id TEXT,
                multi_step_group TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_timestamp
            ON command_history(timestamp DESC)
        """)
        conn.commit()
        return conn

    # ── Sync implementations ──────────────────────────────────────────────

    def _record_sync(
        self,
        action: str,
        parameters: dict[str, Any],
        result: Optional[dict],
        prev_window: Optional[str],
        conversation_id: Optional[str],
        multi_step_group: Optional[str],
    ) -> str:
        entry_id = str(uuid.uuid4())
        reversible, undo_action, undo_params = _compute_undo(action, parameters, prev_window)

        with self._lock:
            self._conn.execute(
                """INSERT INTO command_history
                   (entry_id, timestamp, action, parameters, result,
                    reversible, undo_action, undo_parameters,
                    conversation_id, multi_step_group)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id,
                    datetime.now(timezone.utc).isoformat(),
                    action,
                    json.dumps(parameters),
                    json.dumps(result) if result is not None else None,
                    1 if reversible else 0,
                    undo_action,
                    json.dumps(undo_params) if undo_params is not None else None,
                    conversation_id,
                    multi_step_group,
                ),
            )
            # Prune oldest entries beyond max_entries
            self._conn.execute(
                """DELETE FROM command_history WHERE entry_id NOT IN
                   (SELECT entry_id FROM command_history ORDER BY timestamp DESC LIMIT ?)""",
                (self._max_entries,),
            )
            self._conn.commit()
        return entry_id

    def _last_undoable_sync(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                """SELECT entry_id, action, parameters, undo_action, undo_parameters
                   FROM command_history
                   WHERE reversible = 1 AND undone = 0
                   ORDER BY timestamp DESC LIMIT 1""",
            ).fetchone()
        if not row:
            return None
        return {
            "entry_id": row[0],
            "action": row[1],
            "parameters": json.loads(row[2]),
            "undo_action": row[3],
            "undo_parameters": json.loads(row[4]) if row[4] else None,
        }

    def _mark_undone_sync(self, entry_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE command_history SET undone = 1 WHERE entry_id = ?",
                (entry_id,),
            )
            self._conn.commit()

    def _recent_sync(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT entry_id, timestamp, action, parameters, result,
                          reversible, undone, multi_step_group
                   FROM command_history
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "entry_id": r[0],
                "timestamp": r[1],
                "action": r[2],
                "parameters": json.loads(r[3]),
                "result": json.loads(r[4]) if r[4] else None,
                "reversible": bool(r[5]),
                "undone": bool(r[6]),
                "multi_step_group": r[7],
            }
            for r in rows
        ]

    def _clear_sync(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM command_history")
            self._conn.commit()

    # ── Async wrappers ────────────────────────────────────────────────────

    async def record(
        self,
        action: str,
        parameters: dict[str, Any],
        result: Optional[dict] = None,
        prev_window: Optional[str] = None,
        conversation_id: Optional[str] = None,
        multi_step_group: Optional[str] = None,
    ) -> str:
        """Record an executed command and compute its undo operation.

        Args:
            action: The direct bridge action that was executed.
            parameters: The action parameters dict.
            result: Optional result dict returned by the bridge.
            prev_window: Foreground window title before the action fired.
            conversation_id: Chat conversation that triggered the action.
            multi_step_group: UUID grouping sequential multi-step commands.

        Returns:
            The generated entry_id UUID string.
        """
        return await asyncio.to_thread(
            self._record_sync,
            action,
            parameters,
            result,
            prev_window,
            conversation_id,
            multi_step_group,
        )

    async def last_undoable(self) -> Optional[dict]:
        """Return the most recent reversible command that has not been undone.

        Returns:
            Dict with entry_id, action, parameters, undo_action, undo_parameters,
            or None when no undoable entry exists.
        """
        return await asyncio.to_thread(self._last_undoable_sync)

    async def mark_undone(self, entry_id: str) -> None:
        """Mark a history entry as undone so it cannot be undone again.

        Args:
            entry_id: The UUID of the entry to mark.
        """
        await asyncio.to_thread(self._mark_undone_sync, entry_id)

    async def recent(self, limit: int = 20) -> list[dict]:
        """Return the most recent command history entries.

        Args:
            limit: Maximum number of entries to return (default 20).

        Returns:
            List of entry dicts ordered newest-first.
        """
        return await asyncio.to_thread(self._recent_sync, limit)

    async def clear(self) -> None:
        """Delete all command history entries."""
        await asyncio.to_thread(self._clear_sync)
