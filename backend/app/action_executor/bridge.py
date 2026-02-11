"""Bridge action executor — sends commands to the Windows collector via CommandBridge."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..schemas import TaskAction
from .base import ActionExecutionResult, TaskActionExecutor

if TYPE_CHECKING:
    from ..desktop_context import DesktopContext

logger = logging.getLogger(__name__)


class BridgeActionExecutor(TaskActionExecutor):
    """Executor that sends commands to the Windows collector via CommandBridge."""

    mode = "bridge"

    def __init__(
        self,
        bridge,
        timeout_s: int = 10,
        ollama=None,
    ) -> None:
        self._bridge = bridge
        self._timeout_s = max(1, int(timeout_s))
        self._ollama = ollama

    async def execute(
        self,
        action: TaskAction,
        *,
        objective: str,
        desktop_context: Optional[DesktopContext] = None,
    ) -> ActionExecutionResult:
        if not self._bridge.connected:
            return ActionExecutionResult(
                ok=False,
                error="bridge not connected to collector",
                result={"executor": self.mode, "action": action.action, "ok": False},
            )

        name = (action.action or "").strip()
        params = dict(action.parameters or {})

        try:
            if name == "observe_desktop":
                result = await self._bridge.execute("observe", timeout_s=self._timeout_s)
            elif name == "open_application":
                result = await self._bridge.execute(
                    "open_application",
                    {"application": params.get("application", "")},
                    timeout_s=self._timeout_s,
                )
            elif name == "click":
                result = await self._bridge.execute("click", params, timeout_s=self._timeout_s)
            elif name == "type_text":
                result = await self._bridge.execute("type_text", params, timeout_s=self._timeout_s)
            elif name == "send_keys" or name == "focus_search" or name == "send_or_submit":
                keys = params.get("keys", "")
                result = await self._bridge.execute("send_keys", {"keys": keys}, timeout_s=self._timeout_s)
            elif name == "compose_text":
                text = params.get("text", "")
                if not text and self._ollama and desktop_context:
                    text = await self._generate_compose_text(objective, desktop_context)
                if text:
                    result = await self._bridge.execute(
                        "type_text", {"text": text}, timeout_s=self._timeout_s,
                    )
                else:
                    result = {"ok": False, "error": "no text to compose"}
            elif name == "focus_window":
                result = await self._bridge.execute("focus_window", params, timeout_s=self._timeout_s)
            elif name == "verify_outcome":
                result = await self._bridge.execute("observe", timeout_s=self._timeout_s)
            else:
                result = await self._bridge.execute(name, params, timeout_s=self._timeout_s)
        except Exception as exc:
            return ActionExecutionResult(
                ok=False,
                error=str(exc),
                result={"executor": self.mode, "action": name, "ok": False},
            )

        ok = bool(result.get("ok", False))
        return ActionExecutionResult(
            ok=ok,
            result={
                "executor": self.mode,
                "action": name,
                "ok": ok,
                "bridge_result": result.get("result"),
                "screenshot_available": result.get("screenshot_b64") is not None,
            },
            error=result.get("error"),
        )

    async def _generate_compose_text(self, objective: str, desktop_context) -> str:
        try:
            prompt = (
                f"Draft a concise response for the following objective.\n\n"
                f"Objective: {objective}\n\n"
                f"Desktop Context:\n{desktop_context.to_llm_prompt()}\n\n"
                f"Write only the text to type. No explanation."
            )
            messages = [{"role": "user", "content": prompt}]
            screenshot_bytes = desktop_context.get_screenshot_bytes()
            if screenshot_bytes and hasattr(self._ollama, "chat_with_images"):
                result = await self._ollama.chat_with_images(messages, [screenshot_bytes])
            elif hasattr(self._ollama, "chat"):
                result = await self._ollama.chat(messages)
            else:
                result = await self._ollama.generate(prompt)
            if result and result.strip():
                return result.strip()
        except Exception as exc:
            logger.warning("BridgeExecutor compose_text LLM failed: %s", exc)
        return ""

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "available": self._bridge.connected,
            "bridge_connected": self._bridge.connected,
            "timeout_s": self._timeout_s,
            "message": "Bridge executor connected." if self._bridge.connected else "Bridge executor: collector not connected.",
        }
