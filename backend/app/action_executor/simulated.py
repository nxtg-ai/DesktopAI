"""Simulated (no-op) action executor for testing and fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from ..schemas import TaskAction
from .base import ActionExecutionResult, TaskActionExecutor

if TYPE_CHECKING:
    from ..desktop_context import DesktopContext


class SimulatedTaskActionExecutor(TaskActionExecutor):
    mode = "simulated"

    async def execute(
        self,
        action: TaskAction,
        *,
        objective: str,
        desktop_context: Optional[DesktopContext] = None,
    ) -> ActionExecutionResult:
        return ActionExecutionResult(
            ok=True,
            result={
                "executor": "backend-simulated",
                "mode": self.mode,
                "action": action.action,
                "objective": objective,
                "ok": True,
            },
        )

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "available": True,
            "message": "Simulated deterministic executor active.",
        }

    async def preflight(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "ok": True,
            "checks": [
                {
                    "name": "simulated_mode",
                    "ok": True,
                    "detail": "Deterministic simulated executor active.",
                }
            ],
            "message": "Simulated executor ready.",
        }
