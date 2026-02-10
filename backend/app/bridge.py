"""Bidirectional command bridge between Python backend and Rust Windows collector."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class CommandBridge:
    """Sends commands to the Windows collector via the /ingest WebSocket and awaits results."""

    def __init__(self, default_timeout_s: float = 10.0) -> None:
        self._ws: Optional[WebSocket] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._default_timeout_s = max(1.0, float(default_timeout_s))

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def attach(self, ws: WebSocket) -> None:
        self._ws = ws
        logger.info("CommandBridge: collector attached")

    def detach(self) -> None:
        self._ws = None
        # Cancel all pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("CommandBridge: collector detached")

    async def execute(
        self,
        action: str,
        parameters: Optional[Dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("CommandBridge: not connected to collector")

        command_id = str(uuid4())
        timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[command_id] = future

        command = {
            "type": "command",
            "command_id": command_id,
            "action": action,
            "parameters": parameters or {},
            "timeout_ms": int(timeout * 1000),
        }

        try:
            await self._ws.send_json(command)
        except Exception as exc:
            self._pending.pop(command_id, None)
            raise RuntimeError(f"CommandBridge: failed to send command: {exc}") from exc

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(command_id, None)
            raise
        finally:
            self._pending.pop(command_id, None)

        return result

    def handle_result(self, data: Dict[str, Any]) -> bool:
        command_id = data.get("command_id", "")
        future = self._pending.get(command_id)
        if future is None:
            logger.warning("CommandBridge: received result for unknown command_id=%s", command_id)
            return False
        if not future.done():
            future.set_result(data)
        return True

    def status(self) -> Dict[str, Any]:
        return {
            "connected": self.connected,
            "pending_commands": len(self._pending),
        }
