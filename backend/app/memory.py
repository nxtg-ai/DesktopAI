"""SQLite-backed trajectory storage for agent memory and experience replay."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .vision_agent import AgentStep

_OUTCOME_LABELS = {
    "completed": "COMPLETED",
    "failed": "FAILED",
    "max_iterations": "MAX_ITERATIONS",
}


@dataclass
class ErrorLesson:
    """A learned lesson from a failed trajectory step."""

    objective: str
    action: str
    error: str
    reasoning: str
    trajectory_id: str


def format_trajectory_context(
    trajectories: List[Trajectory],
    max_chars: int = 1500,
) -> str:
    """Format past trajectories into a prompt-injectable string."""
    if not trajectories:
        return ""

    parts: List[str] = []
    for traj in trajectories:
        label = _OUTCOME_LABELS.get(traj.outcome, traj.outcome.upper())
        header = f"[{label}] \"{traj.objective}\" ({traj.step_count} steps)"

        try:
            steps_data = json.loads(traj.steps_json)
        except (json.JSONDecodeError, TypeError):
            steps_data = []

        step_lines: List[str] = []
        for i, step in enumerate(steps_data[:8]):
            action = step.get("action", "?")
            reasoning = str(step.get("reasoning", ""))[:60]
            error = step.get("error")
            line = f"  {i+1}. {action}"
            if reasoning:
                line += f" — {reasoning}"
            if error:
                line += f" [ERR: {str(error)[:40]}]"
            step_lines.append(line)

        entry = header
        if step_lines:
            entry += "\n" + "\n".join(step_lines)
        parts.append(entry)

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 3] + "..."
    return result


def format_error_lessons(
    lessons: List[ErrorLesson],
    max_chars: int = 800,
) -> str:
    """Format error lessons into a prompt-injectable 'avoid these mistakes' section."""
    if not lessons:
        return ""

    parts: List[str] = []
    for lesson in lessons:
        line = (
            f"- When trying to \"{lesson.objective[:60]}\", "
            f"action '{lesson.action}' failed: {lesson.error[:80]}"
        )
        if lesson.reasoning:
            line += f" (was attempting: {lesson.reasoning[:60]})"
        parts.append(line)

    result = "LESSONS FROM PAST FAILURES (avoid repeating these mistakes):\n" + "\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 3] + "..."
    return result


@dataclass
class Trajectory:
    trajectory_id: str
    objective: str
    steps_json: str
    outcome: str  # "completed", "failed", "max_iterations"
    step_count: int
    created_at: str


class TrajectoryStore:
    """SQLite-backed trajectory memory for vision agent runs."""

    def __init__(self, path: str, max_trajectories: int = 500) -> None:
        self._path = path
        self._max_trajectories = max_trajectories
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
                CREATE TABLE IF NOT EXISTS trajectories (
                    trajectory_id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    step_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_trajectories_created_at "
                "ON trajectories(created_at)"
            )
            # FTS5 virtual table for full-text search on objectives
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS trajectories_fts
                USING fts5(objective, content=trajectories, content_rowid=rowid)
                """
            )
            # Triggers to keep FTS in sync
            cur.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS trajectories_ai AFTER INSERT ON trajectories BEGIN
                    INSERT INTO trajectories_fts(rowid, objective) VALUES (new.rowid, new.objective);
                END;
                CREATE TRIGGER IF NOT EXISTS trajectories_ad AFTER DELETE ON trajectories BEGIN
                    INSERT INTO trajectories_fts(trajectories_fts, rowid, objective) VALUES ('delete', old.rowid, old.objective);
                END;
                CREATE TRIGGER IF NOT EXISTS trajectories_au AFTER UPDATE ON trajectories BEGIN
                    INSERT INTO trajectories_fts(trajectories_fts, rowid, objective) VALUES ('delete', old.rowid, old.objective);
                    INSERT INTO trajectories_fts(rowid, objective) VALUES (new.rowid, new.objective);
                END;
                """
            )
            self._conn.commit()

    async def save_trajectory(
        self,
        trajectory_id: str,
        objective: str,
        steps: List[AgentStep],
        outcome: str,
    ) -> Trajectory:
        return await asyncio.to_thread(
            self._save_trajectory, trajectory_id, objective, steps, outcome
        )

    def _save_trajectory(
        self,
        trajectory_id: str,
        objective: str,
        steps: List[AgentStep],
        outcome: str,
    ) -> Trajectory:
        steps_data = []
        for step in steps:
            entry = {
                "action": step.action.action,
                "parameters": step.action.parameters,
                "reasoning": step.action.reasoning,
                "confidence": step.action.confidence,
                "error": step.error,
            }
            if step.result:
                entry["result_ok"] = step.result.get("ok", True)
            steps_data.append(entry)

        now = datetime.now(timezone.utc).isoformat()
        trajectory = Trajectory(
            trajectory_id=trajectory_id,
            objective=objective,
            steps_json=json.dumps(steps_data),
            outcome=outcome,
            step_count=len(steps),
            created_at=now,
        )

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO trajectories (trajectory_id, objective, steps_json, outcome, step_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trajectory_id) DO UPDATE SET
                    steps_json = excluded.steps_json,
                    outcome = excluded.outcome,
                    step_count = excluded.step_count
                """,
                (
                    trajectory.trajectory_id,
                    trajectory.objective,
                    trajectory.steps_json,
                    trajectory.outcome,
                    trajectory.step_count,
                    trajectory.created_at,
                ),
            )
            self._apply_retention(cur)
            self._conn.commit()

        return trajectory

    async def find_similar(self, objective: str, limit: int = 3) -> List[Trajectory]:
        return await asyncio.to_thread(self._find_similar, objective, limit)

    def _find_similar(self, objective: str, limit: int) -> List[Trajectory]:
        if limit <= 0:
            return []
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT t.trajectory_id, t.objective, t.steps_json, t.outcome,
                       t.step_count, t.created_at
                FROM trajectories_fts fts
                JOIN trajectories t ON t.rowid = fts.rowid
                WHERE trajectories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (objective, limit),
            ).fetchall()
        return [self._row_to_trajectory(row) for row in rows]

    async def list_trajectories(self, limit: int = 20) -> List[Trajectory]:
        return await asyncio.to_thread(self._list_trajectories, limit)

    def _list_trajectories(self, limit: int) -> List[Trajectory]:
        if limit <= 0:
            return []
        with self._lock:
            cur = self._conn.cursor()
            rows = cur.execute(
                """
                SELECT trajectory_id, objective, steps_json, outcome, step_count, created_at
                FROM trajectories
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_trajectory(row) for row in rows]

    async def get_trajectory(self, trajectory_id: str) -> Optional[Trajectory]:
        return await asyncio.to_thread(self._get_trajectory, trajectory_id)

    def _get_trajectory(self, trajectory_id: str) -> Optional[Trajectory]:
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute(
                """
                SELECT trajectory_id, objective, steps_json, outcome, step_count, created_at
                FROM trajectories
                WHERE trajectory_id = ?
                """,
                (trajectory_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_trajectory(row)

    async def extract_error_lessons(
        self, objective: str, limit: int = 5
    ) -> List[ErrorLesson]:
        """Extract error patterns from failed trajectories similar to the given objective."""
        return await asyncio.to_thread(self._extract_error_lessons, objective, limit)

    def _extract_error_lessons(self, objective: str, limit: int) -> List[ErrorLesson]:
        if limit <= 0:
            return []

        with self._lock:
            cur = self._conn.cursor()
            # First try FTS match, fall back to recent failures
            try:
                rows = cur.execute(
                    """
                    SELECT t.trajectory_id, t.objective, t.steps_json
                    FROM trajectories_fts fts
                    JOIN trajectories t ON t.rowid = fts.rowid
                    WHERE trajectories_fts MATCH ? AND t.outcome = 'failed'
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (objective, limit),
                ).fetchall()
            except Exception:
                rows = []

            if not rows:
                rows = cur.execute(
                    """
                    SELECT trajectory_id, objective, steps_json
                    FROM trajectories
                    WHERE outcome = 'failed'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        lessons: List[ErrorLesson] = []
        for row in rows:
            try:
                steps_data = json.loads(row["steps_json"])
            except (json.JSONDecodeError, TypeError):
                continue

            for step in steps_data:
                error = step.get("error")
                if not error:
                    result_ok = step.get("result_ok", True)
                    if result_ok:
                        continue
                    error = "action reported failure"

                lessons.append(
                    ErrorLesson(
                        objective=row["objective"],
                        action=step.get("action", "unknown"),
                        error=str(error),
                        reasoning=str(step.get("reasoning", "")),
                        trajectory_id=row["trajectory_id"],
                    )
                )

        return lessons[:limit]

    def _apply_retention(self, cur: sqlite3.Cursor) -> None:
        if self._max_trajectories <= 0:
            return
        count_row = cur.execute("SELECT COUNT(*) AS count FROM trajectories").fetchone()
        if not count_row or count_row["count"] <= self._max_trajectories:
            return
        to_delete = count_row["count"] - self._max_trajectories
        cur.execute(
            """
            DELETE FROM trajectories
            WHERE trajectory_id IN (
                SELECT trajectory_id
                FROM trajectories
                ORDER BY created_at ASC
                LIMIT ?
            )
            """,
            (to_delete,),
        )

    @staticmethod
    def _row_to_trajectory(row: sqlite3.Row) -> Trajectory:
        return Trajectory(
            trajectory_id=row["trajectory_id"],
            objective=row["objective"],
            steps_json=row["steps_json"],
            outcome=row["outcome"],
            step_count=row["step_count"],
            created_at=row["created_at"],
        )
