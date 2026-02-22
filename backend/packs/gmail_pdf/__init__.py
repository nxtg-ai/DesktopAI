"""Gmail PDF Compiler pack — subprocess wrapper + run history store."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PackRunStore:
    """SQLite-backed run history for packs.

    Follows the CommandHistoryStore pattern: threading.Lock, WAL mode,
    asyncio.to_thread, persistent self._conn (safe for :memory: tests).
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = self._connect()

    def _connect(self) -> sqlite3.Connection:
        if not self._path.strip().lower().startswith(":"):
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pack_runs (
                run_id TEXT PRIMARY KEY,
                pack TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                exit_code INTEGER,
                status TEXT NOT NULL DEFAULT 'running',
                args TEXT,
                output_path TEXT,
                stdout TEXT,
                stderr TEXT,
                error TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pack_runs_started
            ON pack_runs(started_at DESC)
        """)
        conn.commit()
        return conn

    # ── Sync implementations ──────────────────────────────────────────────

    def _start_run_sync(self, pack: str, args: dict[str, Any] | None = None) -> str:
        run_id = str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """INSERT INTO pack_runs (run_id, pack, started_at, status, args)
                   VALUES (?, ?, ?, 'running', ?)""",
                (
                    run_id,
                    pack,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(args) if args else None,
                ),
            )
            self._conn.commit()
        return run_id

    def _finish_run_sync(
        self,
        run_id: str,
        *,
        exit_code: int | None = None,
        status: str = "success",
        output_path: str | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """UPDATE pack_runs
                   SET finished_at = ?, exit_code = ?, status = ?,
                       output_path = ?, stdout = ?, stderr = ?, error = ?
                   WHERE run_id = ?""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    exit_code,
                    status,
                    output_path,
                    stdout,
                    stderr,
                    error,
                    run_id,
                ),
            )
            self._conn.commit()

    def _get_run_sync(self, run_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pack_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def _last_run_sync(self, pack: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                """SELECT * FROM pack_runs WHERE pack = ?
                   ORDER BY started_at DESC LIMIT 1""",
                (pack,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def _recent_sync(self, pack: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM pack_runs WHERE pack = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (pack, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "run_id": row[0],
            "pack": row[1],
            "started_at": row[2],
            "finished_at": row[3],
            "exit_code": row[4],
            "status": row[5],
            "args": json.loads(row[6]) if row[6] else None,
            "output_path": row[7],
            "stdout": row[8],
            "stderr": row[9],
            "error": row[10],
        }

    # ── Async wrappers ────────────────────────────────────────────────────

    async def start_run(self, pack: str, args: dict[str, Any] | None = None) -> str:
        return await asyncio.to_thread(self._start_run_sync, pack, args)

    async def finish_run(self, run_id: str, **kwargs) -> None:
        await asyncio.to_thread(self._finish_run_sync, run_id, **kwargs)

    async def get_run(self, run_id: str) -> Optional[dict]:
        return await asyncio.to_thread(self._get_run_sync, run_id)

    async def last_run(self, pack: str) -> Optional[dict]:
        return await asyncio.to_thread(self._last_run_sync, pack)

    async def recent(self, pack: str, limit: int = 20) -> list[dict]:
        return await asyncio.to_thread(self._recent_sync, pack, limit)


# Regex to extract PDF output path from the script's stdout
_PDF_SAVED_RE = re.compile(r"PDF saved to:\s*(.+)", re.I)


class GmailPdfPack:
    """Subprocess wrapper for the Gmail PDF compiler tool.

    Runs the external script in its own venv so weasyprint/google-api deps
    never pollute the backend environment. Uses asyncio.Lock because the
    critical section contains ``await`` calls.
    """

    def __init__(
        self,
        *,
        script_dir: str,
        output_dir: str,
        python_path: str,
        timeout_s: int = 600,
        store: PackRunStore,
    ) -> None:
        self._script_dir = script_dir
        self._output_dir = output_dir
        self._python_path = python_path
        self._timeout_s = timeout_s
        self._store = store
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        """True when the script directory and python interpreter exist."""
        return (
            Path(self._script_dir, "main_pdf.py").is_file()
            and Path(self._python_path).is_file()
        )

    @property
    def store(self) -> PackRunStore:
        return self._store

    async def run(
        self,
        days: int = 1,
        output: str | None = None,
        no_images: bool = False,
        verbose: bool = False,
    ) -> dict:
        """Execute the Gmail PDF compiler.

        Returns a result dict with run_id, status, exit_code, output_path,
        stdout (last 2000 chars), stderr (last 2000 chars).

        Raises RuntimeError if another run is already in progress.
        """
        if self._lock.locked():
            raise RuntimeError("A Gmail PDF compilation is already running.")

        async with self._lock:
            args_record = {
                "days": days,
                "output": output,
                "no_images": no_images,
                "verbose": verbose,
            }
            run_id = await self._store.start_run("gmail_pdf", args_record)

            cmd = [self._python_path, "main_pdf.py", "--days", str(days)]
            if output:
                cmd.extend(["--output", output])
            elif self._output_dir:
                cmd.extend(["--output", self._output_dir])
            if no_images:
                cmd.append("--no-images")
            if verbose:
                cmd.append("--verbose")

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=self._script_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=None,  # inherit parent env (HOME, PATH for OAuth)
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout_s
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()  # type: ignore[union-attr]
                except Exception:
                    pass
                await self._store.finish_run(
                    run_id, exit_code=-1, status="timeout",
                    error=f"Timed out after {self._timeout_s}s",
                )
                return {
                    "run_id": run_id, "status": "timeout",
                    "exit_code": -1, "output_path": None,
                    "stdout": "", "stderr": "",
                }
            except Exception as exc:
                await self._store.finish_run(
                    run_id, exit_code=-1, status="error", error=str(exc),
                )
                return {
                    "run_id": run_id, "status": "error",
                    "exit_code": -1, "output_path": None,
                    "stdout": "", "stderr": str(exc),
                }

            stdout_text = stdout_bytes.decode("utf-8", errors="replace")[-2000:]
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")[-2000:]
            exit_code = proc.returncode or 0

            # Parse output path from stdout
            output_path = None
            m = _PDF_SAVED_RE.search(stdout_text)
            if m:
                output_path = m.group(1).strip()

            status = "success" if exit_code == 0 else "failed"
            await self._store.finish_run(
                run_id,
                exit_code=exit_code,
                status=status,
                output_path=output_path,
                stdout=stdout_text,
                stderr=stderr_text,
            )

            logger.info(
                "gmail_pdf run_id=%s status=%s exit_code=%d output_path=%s",
                run_id, status, exit_code, output_path,
            )

            return {
                "run_id": run_id,
                "status": status,
                "exit_code": exit_code,
                "output_path": output_path,
                "stdout": stdout_text,
                "stderr": stderr_text,
            }
