"""Base types and helpers shared across action executors."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..schemas import TaskAction

if TYPE_CHECKING:
    from ..desktop_context import DesktopContext


def _is_windows_platform() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


@dataclass(frozen=True)
class ActionExecutionResult:
    ok: bool
    result: Dict[str, Any]
    error: Optional[str] = None


class TaskActionExecutor:
    mode: str = "simulated"

    async def execute(
        self,
        action: TaskAction,
        *,
        objective: str,
        desktop_context: Optional[DesktopContext] = None,
    ) -> ActionExecutionResult:
        raise NotImplementedError

    def status(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def preflight(self) -> Dict[str, Any]:
        status = self.status()
        available = bool(status.get("available", False))
        mode = str(status.get("mode", self.mode))
        ok = available or mode == "simulated"
        return {
            "mode": mode,
            "ok": ok,
            "checks": [
                {
                    "name": "executor_available",
                    "ok": ok,
                    "detail": status.get("message", ""),
                }
            ],
            "message": status.get("message", ""),
        }


def _detect_changes(before, after) -> Optional[str]:
    parts = []
    if before.window_title != after.window_title:
        parts.append(f"window changed to {after.window_title!r}")
    if before.uia_summary != after.uia_summary:
        parts.append("UI state changed")
    if not parts:
        return None
    return "; ".join(parts)
