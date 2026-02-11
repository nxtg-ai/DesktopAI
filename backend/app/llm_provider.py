"""LLM provider abstraction for swappable backends (Ollama, OpenAI-compatible)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface for LLM backends used by chat, planning, and execution."""

    async def available(self) -> bool: ...

    async def chat(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        format: Optional[dict] = None,
        timeout_s: float = 30.0,
    ) -> Optional[str]: ...

    async def chat_with_images(
        self,
        messages: list[dict],
        images: list[bytes],
        *,
        model: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> Optional[str]: ...

    async def generate(self, prompt: str) -> Optional[str]: ...


class OpenAIProvider:
    """OpenAI-compatible provider using /v1/chat/completions."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        ttl_seconds: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._ttl = ttl_seconds
        self._last_check = 0.0
        self._available = False
        self._last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def available(self) -> bool:
        now = time.monotonic()
        if now - self._last_check < self._ttl:
            return self._available
        async with self._lock:
            now = time.monotonic()
            if now - self._last_check < self._ttl:
                return self._available
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{self.base_url}/models",
                        headers=self._headers(),
                    )
                self._available = resp.status_code == 200
                self._last_error = (
                    None if self._available else f"models returned {resp.status_code}"
                )
            except Exception as exc:
                self._available = False
                self._last_error = str(exc)
            self._last_check = time.monotonic()
            return self._available

    async def _call_chat(
        self,
        messages: list[dict],
        model: str,
        timeout_s: float,
    ) -> Optional[str]:
        payload = {
            "model": model,
            "messages": messages,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except Exception as exc:
            logger.warning("OpenAI chat failed: %s", exc)
            self._last_error = str(exc)
            return None

        if resp.status_code != 200:
            self._last_error = f"chat/completions returned {resp.status_code}"
            logger.warning("OpenAI chat error: %s", self._last_error)
            return None

        try:
            data = resp.json()
        except Exception:
            return None

        choices = data.get("choices", [])
        if not choices:
            return None
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            self._available = True
            self._last_check = time.monotonic()
            return content.strip()
        return None

    async def chat(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        format: Optional[dict] = None,
        timeout_s: float = 30.0,
    ) -> Optional[str]:
        active_model = model or self.model
        return await self._call_chat(messages, active_model, timeout_s)

    async def chat_with_images(
        self,
        messages: list[dict],
        images: list[bytes],
        *,
        model: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> Optional[str]:
        if not messages or not images:
            return None

        # Convert to OpenAI vision format: content becomes array with text + image_url
        messages_copy = [msg.copy() for msg in messages]
        for msg in reversed(messages_copy):
            if msg.get("role") == "user":
                text_content = msg.get("content", "")
                content_parts: list[dict] = [
                    {"type": "text", "text": text_content},
                ]
                for img in images:
                    b64 = base64.b64encode(img).decode("utf-8")
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        }
                    )
                msg["content"] = content_parts
                break

        active_model = model or self.model
        return await self._call_chat(messages_copy, active_model, timeout_s)

    async def generate(self, prompt: str) -> Optional[str]:
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages)

    def diagnostics(self) -> dict:
        return {
            "provider": "openai",
            "available": self._available,
            "base_url": self.base_url,
            "model": self.model,
            "last_error": self._last_error,
            "last_check_at": datetime.now(timezone.utc).isoformat()
            if self._last_check > 0
            else None,
        }
