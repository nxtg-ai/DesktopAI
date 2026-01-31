from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, ttl_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._ttl = ttl_seconds
        self._last_check = 0.0
        self._available: bool = False
        self._lock = asyncio.Lock()

    async def available(self) -> bool:
        now = time.monotonic()
        if now - self._last_check < self._ttl:
            return self._available
        async with self._lock:
            now = time.monotonic()
            if now - self._last_check < self._ttl:
                return self._available
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                self._available = resp.status_code == 200
            except Exception:
                self._available = False
            self._last_check = time.monotonic()
            return self._available

    async def summarize(self, prompt: str) -> Optional[str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("response")
